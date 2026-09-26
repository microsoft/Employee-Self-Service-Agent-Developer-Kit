<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-2 — Provision the Workday Entra App

Role: **App / Cloud Application Administrator** (a **consent-capable** role —
Application Administrator, Cloud Application Administrator, Privileged Role
Administrator, or Global Administrator — is required for the admin-consent step).
This step configures the Microsoft Entra app registration for the Workday SSO
integration so the agent can call Workday on behalf of the signed-in user. It owns
master-checklist rows **DA2.1 through DA2.7**.

Depends on DA-1 (the Workday extension package must already be installed). It is
**Entra-only** — it needs Microsoft Graph, not Dataverse. Everything below is
identical to how a CEA Employee Self-Service agent provisions its Workday Entra
app — Entra app registration doesn't differ by agent architecture — only the
persisted state paths differ.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names or IDs in chat
(e.g. do not print `WD_ENTRA_APP_OBJECT_ID = ...`).

**Graph-first with a portal fallback on every step.** Each configuration step is
attempted through Microsoft Graph (`az rest` / `az ad`); if a Graph call fails for
a permission or tenant-policy reason, fall back to the portal instructions shown
in that step rather than aborting.

**Checkpoints this step drives (run each in isolation):**

| Step | Checkpoint | Gate |
|------|-----------|------|
| DA2.1 | `WD-CONN-102` *(reuse)* — SAML signing-certificate health | prog instantiate; healthy-state MANUAL |
| DA2.2 | `WD-ENTRA-SCOPE-001` — scope exposed + connector pre-authorized + Graph perms | prog |
| DA2.3 | `WD-ENTRA-CONSENT-001` — admin consent granted | prog; escalate to manual |
| DA2.4 | `WD-ASSIGN-001` — enterprise-app user assignment (or not required) | prog |
| DA2.5 | `WD-ENTRA-NAMEID-001` — NameID `claimsMappingPolicy` | prog; degrade to manual |
| DA2.6 | `WD-ENTRA-SIGNOPT-001` — SAML signing option (portal-only) | manual |
| DA2.7 | `WD-CONN-010` *(reuse)* — single-tenant federation alignment | attest |

Run any one with:

```
python scripts/flightcheck/cli.py --checkpoint <ID>
```

**After every checkpoint run, show its result in chat first.** As soon as a
`--checkpoint` run returns, render the result to the user per
[`shared/checklist-updater.md`](shared/checklist-updater.md) §U.0–U.0a — the
compact result table and, for any `MANUAL` (or `Warning` / `NotConfigured`) row,
its full verification steps — **before** you show any later **Message** or ask any
attestation question. Single-checkpoint runs never open the HTML report, so this
in-chat render is the only place the user sees the manual steps; never ask a user
to attest to steps they have not been shown.

**Build order (row order now matches it).** Row **DA2.1** — the SSO gallery app —
is the foundation every other row configures, so it is built first and the rows
are numbered in build order (DA2.1 → DA2.7). Each section below is titled by the
checklist row it completes. **On every resume, always re-run DA2.0 (role gate),
DA2.0b (Workday tenant URL) and DA2.1 (ensure the app exists) first — all
idempotent — before working the first incomplete row.** This is required, not
cosmetic: DA2.2–DA2.4 configure the app through the in-memory
`WD_ENTRA_APP_OBJECT_ID` that only DA2.1 populates, so entering directly at a
later row after a resume would leave it undefined. After re-running DA2.0, DA2.0b
and DA2.1, skip any row whose `setupStatus` state is already `done`.

---

## DA2.0 — Role gate (App / Cloud Application Administrator)

Before querying roles or changing any application, align Azure CLI to the
canonical tenant selected during `/setup`:

1. Read `environment.tenant_id` from `.local/setup/config.json` and save it as
   `SETUP_TENANT_ID`. If it is absent, stop and ask the user to rerun `/setup`;
   never infer the tenant from the current Azure CLI session.
2. Read the active Azure CLI tenant:

   ```
   az account show --query tenantId -o tsv
   ```

3. If it does not exactly equal `SETUP_TENANT_ID`, sign in to the setup tenant:

   ```
   az login --tenant "{SETUP_TENANT_ID}" --use-device-code --allow-no-subscriptions
   ```

4. Re-run `az account show --query tenantId -o tsv`. If it still differs, halt
   before running the role query or any `az ad` / Graph mutation. Persist
   `tenantId = SETUP_TENANT_ID` to
   `.local/connect/workday-da/config.json` only after this verification.

Apply the shared [`shared/permission-gate.md`](shared/permission-gate.md) before
any Entra work, with:

- `REQUIRED_ROLE` = `"Application Administrator"` (or Cloud Application
  Administrator / Privileged Role Administrator / Global Administrator)
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"DA2.1"`
- `ROLE_QUERY` = a Microsoft Graph directory-role membership check for the
  signed-in user:

  ```
  az rest --method GET --url "https://graph.microsoft.com/v1.0/me/memberOf/microsoft.graph.directoryRole?%24select=displayName,roleTemplateId" --query "value[].{displayName:displayName,roleTemplateId:roleTemplateId}" -o json
  ```

  The role is held only when a returned `roleTemplateId` equals one of these
  stable built-in role template IDs:

  - Application Administrator:
    `9b895d92-2cd3-44c7-9d02-a6ac2d5ea5c3`
  - Cloud Application Administrator:
    `158c047a-c907-4556-b7ef-446551a6b5f7`
  - Privileged Role Administrator:
    `e8611ab8-c189-46e8-94e1-60213ab1f814`
  - Global Administrator:
    `62e90394-69f5-4237-9190-012177145e10`

  Do not authorize from `displayName`; it is included only for readable
  evidence. Treat an
  `Insufficient privileges` / `Authorization_RequestDenied` / forbidden response
  as "role not held". If the query errors for an unrelated reason (network, not
  signed in), retry once and then stop. Never downgrade this programmatic role
  gate to self-attestation.

If `GATE_RESULT` is `"stop"`, **halt** — do not continue. Otherwise carry
`GATE_EVIDENCE` forward (recorded when the DA2 rows are updated).

---

## DA2.0b — Capture the Workday tenant URL *(enables deterministic app discovery)*

Knowing the Workday tenant lets DA2.1 pin the **exact** Entra SSO app for this
Workday tenant — the app federated to it carries `http://www.workday.com/{tenant}`
as its SAML identifier — instead of guessing among look-alike "Workday" apps. This
step is **idempotent** and **best-effort**: if the URL isn't handy, skip it and
DA2.1 falls back to an interactive picker.

**If `tenant` is already set** in `.local/connect/workday-da/config.json`, skip
this step — it was captured here on an earlier run, or by DA-3.

Otherwise ask for the Workday URL with the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Workday URL",
    "question": "Paste the address-bar URL from your browser while you're signed in to Workday (for example https://impl.workday.com/yourcompany/d/home.htmld). Don't have it handy? Leave it blank and I'll identify the Workday app another way.",
    "allowFreeformInput": true
  }
]
```

**If the user provides a URL**, parse it silently (do not echo the parsing):

- `WD_TENANT` — the first path segment after the host
  (`https://impl.workday.com/contoso_impl/d/…` → `contoso_impl`).
- `WD_BASE_URL` — the scheme + host (`https://impl.workday.com`).
- `WD_TOKEN_HOST` — the Workday **services** host derived from the web host:
  - `impl.workday.com` → `wd2-impl-services1.workday.com`
  - `wd5.myworkday.com` → `wd5-services1.myworkday.com`
  - `{dcN}.myworkday.com` → `{dcN}-services1.myworkday.com`

  If the host matches no known pattern, keep `WD_TENANT` / `WD_BASE_URL` and leave
  `WD_TOKEN_HOST` for DA-3 to resolve from the API-client token endpoint.

Before persisting or interpolating the tenant, require:

- an `https` URL;
- a non-empty first path segment;
- `WD_TENANT` matches
  `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`.

If any condition fails, reject the value and ask again. Never persist or place
an unvalidated path segment into an `az` command.

**Persist** to `.local/connect/workday-da/config.json` (merge — keep other keys,
per [`shared/config-schema.md`](shared/config-schema.md)): `tenant` =
`WD_TENANT`, `baseUrl` = `WD_BASE_URL`, and `tokenHost` = `WD_TOKEN_HOST` when
derived.

**If the user leaves it blank**, record nothing and continue — DA2.1 will
identify the app by display name and ask you to choose if more than one matches.

---

## DA2.1 — Instantiate the Workday SSO gallery app *(foundation — do this first)*

This creates the single Entra app every other DA2 row configures: the Workday SSO
gallery app, in SAML mode, with a token-signing certificate. It is **idempotent** —
re-running never creates a duplicate.

**First, check whether the app already exists.** Read
`.local/connect/workday-da/config.json`. If `entraAppObjectId` is set, the app was
already created (by this step or by an earlier `/connect workday` run) — load
`WD_ENTRA_APP_OBJECT_ID` (from `entraAppObjectId`), `WD_ENTRA_APP_ID` (from
`entraAppId`), and re-resolve the service-principal id:

```
az ad sp list --filter "appId eq '{WD_ENTRA_APP_ID}'" --query "[0].id" -o tsv
```

Save it as `WD_ENTRA_SP_ID` and skip to **verify (WD-CONN-102)** below.

**If no app is recorded yet**, discover or instantiate it.

**First, when the Workday tenant is known** — DA2.0b recorded `tenant` in
`.local/connect/workday-da/config.json` — pin the app **deterministically** by its
tenant-scoped SAML identifier. The Entra app federated to this Workday tenant
carries `http://www.workday.com/{tenant}` in its `identifierUris`, so no guessing
is needed:

```
$targetIdentifier = "http://www.workday.com/{tenant}"
$normalizedTarget = $targetIdentifier.Trim().TrimEnd('/').ToLowerInvariant()
$apps = az ad app list --all --query "[?identifierUris != null].{name:displayName, appId:appId, id:id, identifierUris:identifierUris}" -o json | ConvertFrom-Json
$matches = @($apps | Where-Object {
  @($_.identifierUris | ForEach-Object {
    ([string]$_).Trim().TrimEnd('/').ToLowerInvariant()
  }) -contains $normalizedTarget
})
```

- Match only normalized **exact equality** as shown above. Never use
  `contains()` or substring matching: a tenant such as `microsoft_dpt6` can
  coexist with `microsoft_dpt6_okta`, and substring matching selects both.
- **Exactly one match** → this is unambiguously the right app. Save its `appId` →
  `WD_ENTRA_APP_ID` and its `id` → `WD_ENTRA_APP_OBJECT_ID`, then resolve the
  service-principal id (`az ad sp list --filter "appId eq '{WD_ENTRA_APP_ID}'"
  --query "[0].id" -o tsv`) → `WD_ENTRA_SP_ID`. **Do not prompt** — skip to
  **Persist** below.
- **More than one match** (rare — two apps carry this tenant's identifier) → use
  the interactive picker described below, but list **only these matches**.
- **No match** → no existing app federates to this Workday tenant; fall through to
  the by-name search below (which normally leads to creating a fresh app).

**Otherwise — the tenant is unknown (DA2.0b was skipped) or the tenant pin found
no match** — look for an existing Workday SAML app by name:

```
az ad sp list --display-name "Workday" --query "[].{name:displayName, appId:appId, id:id, sso:preferredSingleSignOnMode, replyUrls:replyUrls}" -o json
```

- **If one or more Workday SAML apps already exist** — consider only the
  returned apps in SAML mode (`sso == "saml"`). Because tenant identity was not
  established, never auto-select by display name, even when there is exactly
  one match. The app chosen here is pinned to `entraAppId` in config, and every
  later step and FlightCheck check (consent, user assignment, NameID) keys off
  it — picking the wrong sibling makes a correctly-configured app report
  FAILED. Ask the user to choose. Use the `vscode_askQuestions` tool, building
  the `options` array **dynamically from the returned SAML apps** — one option
  per app, plus a final "Create a new app instead" option:

    ```json
    [
      {
        "header": "Workday Entra app",
        "question": "I found more than one Workday enterprise app in your tenant. Which one should ESS use for Workday single sign-on?",
        "options": [
          { "label": "Workday (ESS Copilot)", "description": "SAML · reply URL https://…/ess · provisioned by this kit", "recommended": true },
          { "label": "Create a new app instead", "description": "Provision a fresh \"Workday (ESS Copilot)\" app from the gallery" }
        ],
        "allowFreeformInput": false
      }
    ]
    ```

  Emit one option object per returned SAML app. Build a label-to-app mapping
  before asking. If a display name is unique, use it as the label. If two or
  more apps share a display name, make each **label itself** unique by
  appending `· {last 6 characters of appId}`. Set `description` to its SSO
  mode plus first reply URL; never include a full app/object GUID. Mark the
  option for the kit-provisioned **`Workday (ESS Copilot)`** app as
  `recommended` when unambiguous. Then:
  - **User picks an existing app** → use the retained label-to-app mapping
    (never a display-name search) to map the unique chosen label to that app and
    save its `appId` → `WD_ENTRA_APP_ID` and its `id` (the service-principal
    id) → `WD_ENTRA_SP_ID`, then resolve its **application** object id — the
    `az ad sp list` results carry the *service-principal* id, **not** the app
    object id, so query it explicitly:

    ```
    az ad app list --filter "appId eq '{WD_ENTRA_APP_ID}'" --query "[0].id" -o tsv
    ```

    → `WD_ENTRA_APP_OBJECT_ID`. Then **skip to Persist below** so `entraAppId`
    is written to config — do **not** jump ahead to verify.
  - **User picks "Create a new app instead"** → follow the **If none exists**
      instantiate path below.

- **If none exists**, instantiate from the Workday gallery template. Find the
  template id, then instantiate it:

  ```
  az rest --method GET --url "https://graph.microsoft.com/v1.0/applicationTemplates?%24filter=displayName%20eq%20'Workday'" --query "value[0].id" -o tsv
  ```

  ```powershell
  $body = @{displayName="Workday (ESS Copilot)"} | ConvertTo-Json
  $body | Out-File "$env:TEMP\ess-wd-template.json" -Encoding utf8
  az rest --method POST --url "https://graph.microsoft.com/v1.0/applicationTemplates/{TEMPLATE_ID}/instantiate" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-wd-template.json"
  ```

  From the response, save `application.appId` → `WD_ENTRA_APP_ID`,
  `application.id` → `WD_ENTRA_APP_OBJECT_ID`, `servicePrincipal.id` →
  `WD_ENTRA_SP_ID`. Then set SAML mode, the identifier/reply URLs, and add **and
  activate** a token-signing certificate (set
  `preferredSingleSignOnMode = "saml"`, `identifierUris`/`web.redirectUris`, then
  `addTokenSigningCertificate` and set `preferredTokenSigningKeyThumbprint` to
  activate it — capture the thumbprint + expiry).

  **Portal fallback (permission error on instantiate/PATCH):**

  **Message:**

  I need permission to create and configure enterprise applications in your Entra
  tenant, which requires the **Application Administrator** or **Cloud Application
  Administrator** role. If you can't get that role, ask your IT admin to create a
  Workday enterprise app from the Entra gallery (SAML mode, with a token-signing
  certificate) and share its Application ID with you, then tell me and I'll pick
  it up from there.

  **End message.**

  Wait for the user, then re-resolve the app with the `az ad sp list` filter above.

**Persist** the app identity to `.local/connect/workday-da/config.json` (merge —
keep other keys, per [`shared/config-schema.md`](shared/config-schema.md)):

- `entraAppId` = `WD_ENTRA_APP_ID`
- `entraAppObjectId` = `WD_ENTRA_APP_OBJECT_ID`

**Verify (WD-CONN-102):**

This is the **first FlightCheck checkpoint in this skill that uses Microsoft
Graph**. FlightCheck signs in to Graph with its **own** token — separate from the
`az` sign-in used to create the app above and from the earlier environment
sign-in — so the command below **opens a browser window for a Microsoft Graph
sign-in** the first time it runs. Show the message first, then run the command.
Do **not** wait for a chat reply before running it, and do **not** cancel or
re-run the command while it appears to pause: it is **blocked on the browser
sign-in, not hung**, and returns on its own once the sign-in completes. (Later
Graph checkpoints reuse this token and run silently.)

**Message (do NOT wait for a response — continue immediately):**

I'm running the first readiness check now — it confirms the single sign-on signing
certificate for your Workday app is present and healthy. A browser window will open
for a Microsoft Graph sign-in — please complete it with the same admin account, and
I'll continue automatically once it finishes.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-CONN-102 --connect-config ".local/connect/workday-da/config.json"
```

`WD-CONN-102` reports the Entra-side signing-certificate health. It returns
`MANUAL` for the healthy state because Workday-side certificate parity is verified
later in DA-3 (row DA3.4). Present the certificate/thumbprint result to the
user, then update **DA2.1** via
[`shared/checklist-updater.md`](shared/checklist-updater.md) with
`STEP_ID="DA2.1"`, `GATE="manual"`, `CHECKPOINT_RESULT` = the checkpoint result,
and `ACK` = the user's explicit confirmation that the certificate was added and
activated. Pass the certificate thumbprint and activation confirmation as
`ROW_EVIDENCE`, and persist the DA2.0 `GATE_EVIDENCE`.

---

## DA2.2 — Expose the API scope, pre-authorize the connector, grant Graph perms

Configure the app (`WD_ENTRA_APP_OBJECT_ID` from DA2.1) so the Power Platform
Workday connector can obtain an on-behalf-of token.

1. **Expose the `user_impersonation` scope without replacing the SAML
   identifier.** The application must retain both distinct identifier URIs:
   `http://www.workday.com/{tenant}` for Workday SAML and
   `api://{WD_ENTRA_APP_ID}` for the exposed API scope. Do not call the generic
   B.4a command because it replaces the entire `identifierUris` collection.
   PATCH the application with both exact values, generate `SCOPE_GUID`, then
   apply
   [`connect/azure/app-registration.md`](../../connect/azure/app-registration.md)
   **§B.4b** to expose `user_impersonation`.

2. **Pre-authorize the Workday connector** — apply the same file's **§B.5** with
   `CONNECTOR_APP_ID` = `4e4707ca-5f53-46a6-a819-f7765446e6ff` (the Power Platform
   **Workday** connector — never the ServiceNow `c26b24aa`), `APP_OBJECT_ID` =
   `WD_ENTRA_APP_OBJECT_ID`, and the `SCOPE_GUID` from step 1.

3. **Add the Graph delegated permissions** `openid`, `profile`, `User.Read`:

   ```powershell
   $body = @{requiredResourceAccess=@(@{
     resourceAppId="00000003-0000-0000-c000-000000000000"
     resourceAccess=@(
       @{ id="37f7f235-527c-4136-accd-4a02d197296e"; type="Scope" }
       @{ id="14dad69e-099b-42c9-810b-d002981feec1"; type="Scope" }
       @{ id="e1fe6dd8-ba31-4d61-89e7-88639da4683d"; type="Scope" }
     )
   })} | ConvertTo-Json -Depth 6
   $body | Out-File "$env:TEMP\ess-wd-graphperms.json" -Encoding utf8
   az rest --method PATCH --url "https://graph.microsoft.com/v1.0/applications/{WD_ENTRA_APP_OBJECT_ID}" --headers "Content-Type=application/json" --body "@$env:TEMP\ess-wd-graphperms.json"
   ```

   **Portal fallback (PATCH fails):**

   **Message:**

   I couldn't add the Microsoft Graph permissions automatically. You can add them
   in the portal: open https://entra.microsoft.com → **App registrations** → your
   Workday app → **API permissions** → **Add a permission** → **Microsoft Graph**
   → **Delegated permissions** → add **openid**, **profile**, and **User.Read**.
   Type **done** when you're finished.

   **End message.**

   Wait for the user, then continue.

**Persist** to `.local/connect/workday-da/config.json` (merge): `scopeGuid` =
`SCOPE_GUID`, `entraAppIdUri` = `api://{WD_ENTRA_APP_ID}`,
`workdaySamlEntityId` = `http://www.workday.com/{tenant}`, and `entraSSO` =
`true`. These two URI fields are independent and must never be aliases.

**Message:**

Now I'll verify the Workday app exposes its API permission and that the Power
Platform Workday connector is pre-authorized to call it.

**End message.**

**Verify (WD-ENTRA-SCOPE-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-ENTRA-SCOPE-001 --connect-config ".local/connect/workday-da/config.json"
```

- **`PASSED`** → update **DA2.2** via
  [`shared/checklist-updater.md`](shared/checklist-updater.md) with
  `STEP_ID="DA2.2"`, `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`; persist
  `GATE_EVIDENCE`. Continue to DA2.3.
- **`FAILED`** → the result names which of the three (scope / pre-authorization /
  Graph perms) is missing. Redo that step (Graph or portal fallback), then re-run
  the checkpoint. Keep DA2.2 `in-progress` until it passes.
- **`WARNING` / `SKIPPED`** → surface the message; re-run once. A `SKIPPED` means
  Graph auth or the app couldn't be resolved — confirm DA2.1 completed first.

---

## DA2.3 — Grant admin consent for the Graph delegated permissions

Grant tenant-wide admin consent so the on-behalf-of handshake works for all end
users. Attempt it through Graph; if the caller lacks a consent-capable role,
**escalate to manual consent** rather than hard-failing.

Grant admin consent for the app's service principal (portal is the reliable path;
attempt the portal/`az` grant):

**Message:**

Now I need an administrator to grant consent for the Workday app's permissions.
Open https://entra.microsoft.com → **Enterprise applications** → the **Workday
(ESS Copilot)** app → **Permissions** → **Grant admin consent for
&lt;your tenant&gt;**, then approve the prompt. This needs a consent-capable role
(Application Administrator, Cloud Application Administrator, Privileged Role
Administrator, or Global Administrator). Type **done** when the consent is granted.

**End message.**

Wait for the user, then verify.

**Message:**

Now I'll confirm that admin consent was recorded for the Workday app's
permissions.

**End message.**

**Verify (WD-ENTRA-CONSENT-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-ENTRA-CONSENT-001 --connect-config ".local/connect/workday-da/config.json"
```

- **`PASSED`** → update **DA2.3** via
  [`shared/checklist-updater.md`](shared/checklist-updater.md) with
  `STEP_ID="DA2.3"`, `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to
  DA2.4.
- **`FAILED`** → consent isn't recorded yet.

  **Message:**

  I don't see admin consent for the Workday app's Graph permissions yet. If you
  don't hold a consent-capable role (Application Administrator, Cloud Application
  Administrator, Privileged Role Administrator, or Global Administrator), ask an
  administrator to run **Grant admin consent** on the Workday enterprise app, then
  tell me and I'll re-check.

  **End message.**

  After the user confirms, re-run the checkpoint. Keep DA2.3 `in-progress`
  (escalated to manual consent) until it passes.

---

## DA2.4 — Enterprise-app user assignment (or confirm not required)

Ensure the Workday enterprise app either does not require user assignment, or has
the ESS user security group assigned — otherwise the OBO handshake fails for end
users at first access.

**Message:**

Now I'll check whether the Workday enterprise app requires user assignment and, if
so, that the right users are assigned.

**End message.**

**Verify (WD-ASSIGN-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-ASSIGN-001 --connect-config ".local/connect/workday-da/config.json"
```

- **`PASSED`** (assignment satisfied via a group, or not required) → update
  **DA2.4** via [`shared/checklist-updater.md`](shared/checklist-updater.md) with
  `STEP_ID="DA2.4"`, `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to
  DA2.5.
- **`FAILED`** (assignment required, nothing assigned):

  **Message:**

  The Workday enterprise app requires user assignment but nothing is assigned yet.
  Open https://entra.microsoft.com → **Enterprise applications** → the Workday app
  → **Users and groups** → **Add user/group**, and assign the ESS user security
  group (preferred over individual users). Type **done** when you've assigned it.

  **End message.**

  After the user confirms, re-run the checkpoint. Keep DA2.4 `in-progress` until
  it passes.
- **`WARNING`** (assignment not required, or only individual users assigned) → this
  is a hardening recommendation, not a blocker. Surface the message; treat a
  passing-with-warning as a `prog` pass for the row only if the underlying state is
  acceptable to the user, otherwise leave `in-progress` and let them assign a group.

---

## DA2.5 — NameID claim mapping (`claimsMappingPolicy`)

Map the SAML NameID claim so the value Workday receives equals the Workday User
Name. Attempt the `claimsMappingPolicy` create + assign through Graph; if the
policy route proves brittle, degrade to the manual portal path.

Create a claimsMappingPolicy that overrides the NameID claim (map to the attribute
that equals the Workday User Name — typically `user.mail` or
`user.userPrincipalName`) and assign it to the Workday service principal
(`WD_ENTRA_SP_ID`) via
`POST /servicePrincipals/{WD_ENTRA_SP_ID}/claimsMappingPolicies/$ref`.

**Portal fallback (policy create/assign fails, or the tenant blocks custom
policies):**

**Message:**

I couldn't set the NameID mapping automatically. You can set it in the portal:
open https://entra.microsoft.com → **Enterprise applications** → the Workday app →
**Single sign-on** → **Attributes &amp; Claims** → edit the **Unique User
Identifier (Name ID)** claim so its source attribute equals the Workday User Name
(commonly **user.mail** or **user.userPrincipalName**). Type **done** when it's
set.

**End message.**

Wait for the user, then verify.

**Message:**

Now I'll verify the single sign-on user identifier (NameID) is mapped to the value
your Workday tenant expects.

**End message.**

**Verify (WD-ENTRA-NAMEID-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-ENTRA-NAMEID-001 --connect-config ".local/connect/workday-da/config.json"
```

- **`PASSED`** (a NameID-overriding policy is assigned) → update **DA2.5** via
  [`shared/checklist-updater.md`](shared/checklist-updater.md) with
  `STEP_ID="DA2.5"`, `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to
  DA2.6.
- **`FAILED`** (no override — Entra sends the default UPN) → if your tenant
  deliberately relies on the default `userPrincipalName` NameID **and** it already
  equals the Workday User Name, this can be attested manually; otherwise create the
  mapping (Graph or portal fallback) and re-run. Keep DA2.5 `in-progress` until
  resolved.
- **`MANUAL`** (the policy route is unreadable — missing `Policy.Read.All`) →
  degrade to a manual portal check: confirm the NameID mapping in the portal
  (steps above), then treat DA2.5 as a `manual` row needing explicit
  acknowledgement via
  [`shared/checklist-updater.md`](shared/checklist-updater.md).

---

## DA2.6 — "Sign SAML response and assertion" signing option *(portal-only)*

This signing option has no documented Graph property, so it is a **manual portal
gate** — a Workday service provider that validates signatures rejects the
assertion if it is set wrong.

**Message:**

Next I'll cover the SAML signing option — this one has to be confirmed in the
portal, because the kit can't read the setting directly.

**End message.**

**Verify (WD-ENTRA-SIGNOPT-001):** this checkpoint always returns `MANUAL` (the kit
cannot read the setting).

```
python scripts/flightcheck/cli.py --checkpoint WD-ENTRA-SIGNOPT-001 --connect-config ".local/connect/workday-da/config.json"
```

Present the checkpoint's instructions — its remediation now names the customer's
own Entra SAML IdP identifiers (Issuer / Entity ID, SSO / Login URL, SP audience,
and federation-metadata URL, derived from the captured `tenantId` and
`entraAppId`) so they can match them against their Workday SP configuration. If the
earlier certificate check (DA2.1 / `WD-CONN-102`) surfaced a signing-certificate
thumbprint, restate it here too so the customer knows exactly which certificate
Workday must trust. Then:

**Message:**

One SAML setting can only be set in the portal. Open https://entra.microsoft.com →
**Enterprise applications** → the Workday app → **Single sign-on** → **SAML
Signing Certificate** → **Edit** → set **Signing Option** to **Sign SAML response
and assertion**, and **Save**. Confirm only this Entra setting here. Workday-side
issuer, service-provider ID, and certificate verification happens in the next
phase, after the Workday-administrator gate. Type **done** when the Entra setting
is saved.

**End message.**

Then, per [`shared/checklist-updater.md`](shared/checklist-updater.md)'s manual
rule, ask for an explicit acknowledgement and update **DA2.6** with
`STEP_ID="DA2.6"`, `GATE="manual"`, `CHECKPOINT_RESULT="MANUAL"`, and `ACK` = the
user's explicit confirmation. Pass the displayed signing-option values and
confirmation as `ROW_EVIDENCE`. On `ACK=true` with that evidence the row becomes
`done`; a `MANUAL` result alone never completes it.

---

## DA2.7 — Confirm single-Entra-tenant federation alignment

Confirm that the selected Workday SAML application belongs to the same Entra
tenant selected during `/setup`. This phase stays Entra-only; it does not ask the
maker to inspect or change Workday before a Workday administrator is available.

**Message:**

Now I'll confirm that the selected Workday sign-in application belongs to this
environment's Microsoft Entra tenant. No Workday portal changes are needed in
this phase.

**End message.**

**Verify (WD-CONN-010):**

```
python scripts/flightcheck/cli.py --checkpoint WD-CONN-010 --connect-config ".local/connect/workday-da/config.json"
```

`WD-CONN-010` summarizes the federated Workday SAML app(s) and their entity IDs.
Present the result and scope the confirmation to the Entra application selected
in DA2.1. Do not ask the maker to open Workday or prove the active Workday IdP
here; DA3.0b performs that comparison after the Workday-administrator gate.
Then — this is an **attest** row — ask the user to confirm that the selected app
is the intended Workday tenant application and update **DA2.7** via
[`shared/checklist-updater.md`](shared/checklist-updater.md) with
`STEP_ID="DA2.7"`, `GATE="attest"`, `CHECKPOINT_RESULT` = the checkpoint result,
and `ACK` = the user's explicit confirmation. Pass the selected application
identity and tenant match as `ROW_EVIDENCE`, and persist the DA2.0
`GATE_EVIDENCE`.

---

## Done

**Message:**

Your Workday Entra app is configured and verified — the API scope, connector
authorization, admin consent, user assignment, NameID mapping, and SAML signing
are all in place. Next we'll configure the Workday tenant side (DA-3).

**End message.**

Rows DA2.1–DA2.7 are now recorded in the checklist. Return control to the
orchestrator (`SKILL.md`) to resume at the next unverified row. Stop here — the
Workday tenant configuration is a separate step.
