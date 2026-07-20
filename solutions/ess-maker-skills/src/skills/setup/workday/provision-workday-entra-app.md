<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 3 — Provision the Workday Entra App

Role: **App / Cloud Application Administrator** (a **consent-capable** role —
Application Administrator, Cloud Application Administrator, Privileged Role
Administrator, or Global Administrator — is required for the admin-consent step).
This skill configures the Microsoft Entra app registration for the Workday SSO
integration so the agent can call Workday on behalf of the signed-in user. It owns
master-checklist rows **S3.1 through S3.7**.

Depends on skill 1 (environment) and skill 2 (base agent installed). It is
**Entra-only** — it needs Microsoft Graph, not Dataverse.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names or IDs in chat
(e.g. do not print `WD_ENTRA_APP_OBJECT_ID = ...`).

**Graph-first with a portal fallback on every step.** Each configuration step is
attempted through Microsoft Graph (`az rest` / `az ad`); if a Graph call fails for
a permission or tenant-policy reason, fall back to the portal instructions shown
in that step rather than aborting.

**Checkpoints this skill drives (run each in isolation):**

| Step | Checkpoint | Gate |
|------|-----------|------|
| S3.1 | `WD-CONN-102` *(reuse)* — SAML signing-certificate health | prog instantiate; healthy-state MANUAL |
| S3.2 | `WD-ENTRA-SCOPE-001` — scope exposed + connector pre-authorized + Graph perms | prog |
| S3.3 | `WD-ENTRA-CONSENT-001` — admin consent granted | prog; escalate to manual |
| S3.4 | `WD-ASSIGN-001` — enterprise-app user assignment (or not required) | prog |
| S3.5 | `WD-ENTRA-NAMEID-001` — NameID `claimsMappingPolicy` | prog; degrade to manual |
| S3.6 | `WD-ENTRA-SIGNOPT-001` — SAML signing option (portal-only) | manual |
| S3.7 | `WD-CONN-010` *(reuse)* — single-tenant federation alignment | attest |

Run any one with:

```
python scripts/flightcheck/cli.py --checkpoint <ID>
```

**After every checkpoint run, show its result in chat first.** As soon as a
`--checkpoint` run returns, render the result to the user per
[`shared/checklist-updater.md`](../shared/checklist-updater.md) §U.0–U.0a — the
compact result table and, for any `MANUAL` (or `Warning` / `NotConfigured`) row,
its full verification steps — **before** you show any later **Message** or ask any
attestation question. Single-checkpoint runs never open the HTML report, so this
in-chat render is the only place the user sees the manual steps; never ask a user
to attest to steps they have not been shown.

**Build order (row order now matches it).** Row **S3.1** — the SSO gallery app — is
the foundation every other row configures, so it is built first and the rows are
numbered in build order (S3.1 → S3.7). Each section below is titled by the checklist
row it completes. **On every resume, always re-run S3.0 (role gate), S3.0b (Workday tenant URL) and S3.1 (ensure
the app exists) first — all idempotent — before working the first incomplete
row.** This is required, not cosmetic: S3.2–S3.4 configure the app through the
in-memory `WD_ENTRA_APP_OBJECT_ID` that only S3.1 populates, so entering directly at
a later row after a resume would leave it undefined. After re-running S3.0, S3.0b and S3.1,
skip any row whose `setupStatus` state is already `done`.

---

## S3.0 — Role gate (App / Cloud Application Administrator)

Apply the shared [`permission-gate.md`](../shared/permission-gate.md) before any
Entra work, with:

- `REQUIRED_ROLE` = `"Application Administrator"` (or Cloud Application
  Administrator / Privileged Role Administrator / Global Administrator / app owner)
- `GATE_MODE` = `"programmatic"`
- `STEP_ID` = `"S3.1"`
- `ROLE_QUERY` = a Microsoft Graph directory-role membership check for the
  signed-in user:

  ```
  az rest --method GET --url "https://graph.microsoft.com/v1.0/me/memberOf?%24select=displayName" --query "value[].displayName" -o json
  ```

  The role is held if the returned role names include **`Application
  Administrator`**, **`Cloud Application Administrator`**, **`Privileged Role
  Administrator`**, or **`Global Administrator`**. Treat an
  `Insufficient privileges` / `Authorization_RequestDenied` / forbidden response
  as "role not held". If the query errors for an unrelated reason (network, not
  signed in), follow the gate's retry-then-attest fallback — never assume pass.

If `GATE_RESULT` is `"stop"`, **halt** — do not continue. Otherwise carry
`GATE_EVIDENCE` forward (recorded when the S3 rows are updated).

---

## S3.0b — Capture the Workday tenant URL *(enables deterministic app discovery)*

Knowing the Workday tenant lets S3.1 pin the **exact** Entra SSO app for this
Workday tenant — the app federated to it carries `http://www.workday.com/{tenant}`
as its SAML identifier — instead of guessing among look-alike "Workday" apps. This
step is **idempotent** and **best-effort**: if the URL isn't handy, skip it and
S3.1 falls back to an interactive picker.

**If `tenant` is already set** in `.local/connect/workday/config.json`, skip this
step — it was captured here on an earlier run, or by skill-4.

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
  `WD_TOKEN_HOST` for skill-4 to resolve from the API-client token endpoint.

**Persist** to `.local/connect/workday/config.json` (merge — keep other keys, per
[`config-schema.md`](../shared/config-schema.md)): `tenant` = `WD_TENANT`,
`baseUrl` = `WD_BASE_URL`, and `tokenHost` = `WD_TOKEN_HOST` when derived.

**If the user leaves it blank**, record nothing and continue — S3.1 will identify
the app by display name and ask you to choose if more than one matches.

---

## S3.1 — Instantiate the Workday SSO gallery app *(foundation — do this first)*

This creates the single Entra app every other S3 row configures: the Workday SSO
gallery app, in SAML mode, with a token-signing certificate. It is **idempotent** —
re-running never creates a duplicate.

**First, check whether the app already exists.** Read
`.local/connect/workday/config.json`. If `entraAppObjectId` is set, the app was
already created (by this skill or by `/connect workday`) — load
`WD_ENTRA_APP_OBJECT_ID` (from `entraAppObjectId`), `WD_ENTRA_APP_ID` (from
`entraAppId`), and re-resolve the service-principal id:

```
az ad sp list --filter "appId eq '{WD_ENTRA_APP_ID}'" --query "[0].id" -o tsv
```

Save it as `WD_ENTRA_SP_ID` and skip to **verify (WD-CONN-102)** below.

**If no app is recorded yet**, discover or instantiate it.

**First, when the Workday tenant is known** — S3.0b recorded `tenant` in
`.local/connect/workday/config.json` — pin the app **deterministically** by its
tenant-scoped SAML identifier. The Entra app federated to this Workday tenant
carries `http://www.workday.com/{tenant}` in its `identifierUris`, so no guessing
is needed:

```
az ad app list --all --query "[?identifierUris[?contains(@, 'workday.com/{tenant}')]].{name:displayName, appId:appId, id:id, identifierUris:identifierUris}" -o json
```

- **Exactly one match** → this is unambiguously the right app. Save its `appId` →
  `WD_ENTRA_APP_ID` and its `id` → `WD_ENTRA_APP_OBJECT_ID`, then resolve the
  service-principal id (`az ad sp list --filter "appId eq '{WD_ENTRA_APP_ID}'"
  --query "[0].id" -o tsv`) → `WD_ENTRA_SP_ID`. **Do not prompt** — skip to
  **Persist** below.
- **More than one match** (rare — two apps carry this tenant's identifier) → use
  the interactive picker described below, but list **only these matches**.
- **No match** → no existing app federates to this Workday tenant; fall through to
  the by-name search below (which normally leads to creating a fresh app).

**Otherwise — the tenant is unknown (S3.0b was skipped) or the tenant pin found no
match** — look for an existing Workday SAML app by name:

```
az ad sp list --display-name "Workday" --query "[].{name:displayName, appId:appId, id:id, sso:preferredSingleSignOnMode, replyUrls:replyUrls}" -o json
```

- **If Workday SAML app(s) already exist** — consider only the returned apps in
  SAML mode (`sso == "saml"`):

  - **Exactly one** → save its `appId` → `WD_ENTRA_APP_ID` and its `id` (the
    service-principal id) → `WD_ENTRA_SP_ID`, then resolve its **application**
    object id — the `az ad sp list` query above returns the *service-principal*
    id, **not** the app object id, so query it explicitly:

    ```
    az ad app list --filter "appId eq '{WD_ENTRA_APP_ID}'" --query "[0].id" -o tsv
    ```

    → `WD_ENTRA_APP_OBJECT_ID`. Then **skip to Persist below** so `entraAppId` is
    written to config.

  - **More than one** → do **not** guess which is correct. The app chosen here is
    pinned to `entraAppId` in config, and every later step and FlightCheck check
    (consent, user assignment, NameID) keys off it — picking the wrong sibling
    makes a correctly-configured app report FAILED. Ask the user to choose. Use
    the `vscode_askQuestions` tool, building the `options` array **dynamically
    from the returned SAML apps** — one option per app, plus a final "Create a new
    app instead" option:

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

    Emit one option object per returned SAML app: set `label` to the app's
    `displayName` and `description` to its SSO mode plus its first reply URL (a
    human-meaningful disambiguator — do **not** put the full app/object GUID in
    the description; append only the last 6 characters of the `appId` if two apps
    are otherwise indistinguishable). Mark the app named exactly **`Workday (ESS
    Copilot)`** as `recommended` when present — that is the app this kit
    provisions. Then:
    - **User picks an existing app** → map the chosen label back to that app and
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

**Persist** the app identity to `.local/connect/workday/config.json` (merge — keep
other keys, per [`config-schema.md`](../shared/config-schema.md)):

- `entraAppId` = `WD_ENTRA_APP_ID`
- `entraAppObjectId` = `WD_ENTRA_APP_OBJECT_ID`

**Verify (WD-CONN-102):**

This is the **first FlightCheck checkpoint in setup that uses Microsoft Graph**.
FlightCheck signs in to Graph with its **own** token — separate from the `az`
sign-in used to create the app above and from the earlier environment sign-in — so
the command below **opens a browser window for a Microsoft Graph sign-in** the
first time it runs. Show the message first, then run the command. Do **not** wait
for a chat reply before running it, and do **not** cancel or re-run the command
while it appears to pause: it is **blocked on the browser sign-in, not hung**, and
returns on its own once the sign-in completes. (Later Graph checkpoints reuse this
token and run silently.)

**Message (do NOT wait for a response — continue immediately):**

I'm running the first readiness check now — it confirms the single sign-on signing
certificate for your Workday app is present and healthy. A browser window will open
for a Microsoft Graph sign-in — please complete it with the same admin account, and
I'll continue automatically once it finishes.

**End message.**

```
python scripts/flightcheck/cli.py --checkpoint WD-CONN-102
```

`WD-CONN-102` reports the Entra-side signing-certificate health. It returns
`MANUAL` for the healthy state because Workday-side certificate parity is verified
later in skill-4 (row S4.4). Present the certificate/thumbprint result to the
user, then update **S3.1** via [`checklist-updater.md`](../shared/checklist-updater.md)
with `STEP_ID="S3.1"`, `GATE="manual"`,
`CHECKPOINT_RESULT` = the checkpoint result, and `ACK` = the user's explicit
confirmation that the certificate was added and activated. Persist the P3.0
`GATE_EVIDENCE`.

---

## S3.2 — Expose the API scope, pre-authorize the connector, grant Graph perms

Configure the app (`WD_ENTRA_APP_OBJECT_ID` from S3.1) so the Power Platform
Workday connector can obtain an on-behalf-of token.

1. **Expose the `user_impersonation` scope** — apply
   [`connect/azure/app-registration.md`](../../connect/azure/app-registration.md)
   **§B.4** against this app, with `APP_OBJECT_ID` = `WD_ENTRA_APP_OBJECT_ID`,
   `APP_CLIENT_ID` = `WD_ENTRA_APP_ID`, and `SCOPE_RESOURCE_LABEL` = `Workday`.
   That sets the identifier URI `api://{WD_ENTRA_APP_ID}`, generates a
   `SCOPE_GUID`, and exposes `user_impersonation` (with a built-in portal
   fallback).

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

**Persist** to `.local/connect/workday/config.json` (merge): `scopeGuid` =
`SCOPE_GUID`, `appIdUri` = `api://{WD_ENTRA_APP_ID}`, `entraSSO` = `true`.

**Message:**

Now I'll verify the Workday app exposes its API permission and that the Power
Platform Workday connector is pre-authorized to call it.

**End message.**

**Verify (WD-ENTRA-SCOPE-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-ENTRA-SCOPE-001
```

- **`PASSED`** → update **S3.2** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S3.2"`,
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`; persist `GATE_EVIDENCE`. Continue to
  S3.3.
- **`FAILED`** → the result names which of the three (scope / pre-authorization /
  Graph perms) is missing. Redo that step (Graph or portal fallback), then re-run
  the checkpoint. Keep S3.2 `in-progress` until it passes.
- **`WARNING` / `SKIPPED`** → surface the message; re-run once. A `SKIPPED` means
  Graph auth or the app couldn't be resolved — confirm S3.1 completed first.

---

## S3.3 — Grant admin consent for the Graph delegated permissions

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
python scripts/flightcheck/cli.py --checkpoint WD-ENTRA-CONSENT-001
```

- **`PASSED`** → update **S3.3** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S3.3"`,
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to S3.4.
- **`FAILED`** → consent isn't recorded yet.

  **Message:**

  I don't see admin consent for the Workday app's Graph permissions yet. If you
  don't hold a consent-capable role (Application Administrator, Cloud Application
  Administrator, Privileged Role Administrator, or Global Administrator), ask an
  administrator to run **Grant admin consent** on the Workday enterprise app, then
  tell me and I'll re-check.

  **End message.**

  After the user confirms, re-run the checkpoint. Keep S3.3 `in-progress` (escalated
  to manual consent) until it passes.

---

## S3.4 — Enterprise-app user assignment (or confirm not required)

Ensure the Workday enterprise app either does not require user assignment, or has
the ESS user security group assigned — otherwise the OBO handshake fails for end
users at first access.

**Message:**

Now I'll check whether the Workday enterprise app requires user assignment and, if
so, that the right users are assigned.

**End message.**

**Verify (WD-ASSIGN-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-ASSIGN-001
```

- **`PASSED`** (assignment satisfied via a group, or not required) → update
  **S3.4** via [`checklist-updater.md`](../shared/checklist-updater.md) with
  `STEP_ID="S3.4"`, `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to S3.5.
- **`FAILED`** (assignment required, nothing assigned):

  **Message:**

  The Workday enterprise app requires user assignment but nothing is assigned yet.
  Open https://entra.microsoft.com → **Enterprise applications** → the Workday app
  → **Users and groups** → **Add user/group**, and assign the ESS user security
  group (preferred over individual users). Type **done** when you've assigned it.

  **End message.**

  After the user confirms, re-run the checkpoint. Keep S3.4 `in-progress` until it
  passes.
- **`WARNING`** (assignment not required, or only individual users assigned) → this
  is a hardening recommendation, not a blocker. Surface the message; treat a
  passing-with-warning as a `prog` pass for the row only if the underlying state is
  acceptable to the user, otherwise leave `in-progress` and let them assign a group.

---

## S3.5 — NameID claim mapping (`claimsMappingPolicy`)

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
python scripts/flightcheck/cli.py --checkpoint WD-ENTRA-NAMEID-001
```

- **`PASSED`** (a NameID-overriding policy is assigned) → update **S3.5** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S3.5"`,
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`. Continue to S3.6.
- **`FAILED`** (no override — Entra sends the default UPN) → if your tenant
  deliberately relies on the default `userPrincipalName` NameID **and** it already
  equals the Workday User Name, this can be attested manually; otherwise create the
  mapping (Graph or portal fallback) and re-run. Keep S3.5 `in-progress` until
  resolved.
- **`MANUAL`** (the policy route is unreadable — missing `Policy.Read.All`) →
  degrade to a manual portal check: confirm the NameID mapping in the portal
  (steps above), then treat S3.5 as a `manual` row needing explicit acknowledgement
  via [`checklist-updater.md`](../shared/checklist-updater.md).

---

## S3.6 — "Sign SAML response and assertion" signing option *(portal-only)*

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
python scripts/flightcheck/cli.py --checkpoint WD-ENTRA-SIGNOPT-001
```

Present the checkpoint's instructions — its remediation now names the customer's
own Entra SAML IdP identifiers (Issuer / Entity ID, SSO / Login URL, SP audience,
and federation-metadata URL, derived from the captured `tenantId` and
`entraAppId`) so they can match them against their Workday SP configuration. If the
earlier certificate check (S3.1 / `WD-CONN-102`) surfaced a signing-certificate
thumbprint, restate it here too so the customer knows exactly which certificate
Workday must trust. Then:

**Message:**

One SAML setting can only be set in the portal. Open https://entra.microsoft.com →
**Enterprise applications** → the Workday app → **Single sign-on** → **SAML
Signing Certificate** → **Edit** → set **Signing Option** to **Sign SAML response
and assertion**, and **Save**. Then confirm your Workday tenant's SAML IdP is
configured with the **Issuer**, **SSO / Login URL**, and **SP audience** shown in
the check result above, and that it trusts the signing certificate you activated
earlier. Type **done** when it's set.

**End message.**

Then, per [`checklist-updater.md`](../shared/checklist-updater.md)'s manual rule,
ask for an explicit acknowledgement and update **S3.6** with `STEP_ID="S3.6"`,
`GATE="manual"`, `CHECKPOINT_RESULT="MANUAL"`, and `ACK` = the user's explicit
confirmation. On `ACK=true` the row becomes `done`; a `MANUAL` result alone never
completes it.

---

## S3.7 — Confirm single-Entra-tenant federation alignment

Confirm exactly one Entra tenant federates to the Workday tenant ESS uses (a
misaligned or duplicate federation breaks user-context SAML SSO).

**Message:**

Now I'll review the Workday SAML federation to confirm exactly one Entra tenant is
linked to the Workday tenant your agent uses.

**End message.**

**Verify (WD-CONN-010):**

```
python scripts/flightcheck/cli.py --checkpoint WD-CONN-010
```

`WD-CONN-010` summarizes the federated Workday SAML app(s) and their entity IDs.
Present the result, then — this is an **attest** row — ask the user to confirm the
alignment and update **S3.7** via
[`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S3.7"`,
`GATE="attest"`, `CHECKPOINT_RESULT` = the checkpoint result, and `ACK` = the
user's explicit confirmation. Persist the P3.0 `GATE_EVIDENCE`.

---

## Done

**Message:**

Your Workday Entra app is configured and verified — the API scope, connector
authorization, admin consent, user assignment, NameID mapping, and SAML signing
are all in place. Next we'll configure the Workday tenant side (skill 4).

**End message.**

Rows S3.1–S3.7 are now recorded in the checklist. Return control to the
orchestrator (`SKILL.md`) to resume at the next unverified row. Stop here — the
Workday tenant configuration is a separate skill.
