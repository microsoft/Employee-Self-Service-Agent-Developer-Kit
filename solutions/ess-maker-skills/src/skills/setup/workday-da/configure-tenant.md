<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-3 — Configure the Workday Tenant

Role: **Workday Administrator**. This step performs the Workday-tenant-side
configuration the simplified setup requires: the SAML X.509 signing certificate,
Tenant Setup – Security, the Workday API client, and the authentication policy.
It owns master-checklist rows **DA3.1 through DA3.4**.

Depends on DA-2 (the Entra app must already exist — this step reads its
`entraAppId` / `appIdUri` and the activated signing-cert thumbprint). It is
**Workday-only**: none of these tasks is reachable through a Microsoft admin API,
and standing up a Workday connection to self-verify would be **circular** (it
needs the same Entra-app + tenant configuration the ESS agent itself needs). So
every step here is a **manual Workday-admin task**, and its flightcheck reports
`MANUAL` — it echoes what the operator captured and names the Workday screen to
verify, but it never marks a row done on its own. None of this differs from how a
CEA Employee Self-Service agent's Workday tenant is configured — the Workday side
of the connection doesn't know or care what agent architecture is calling it —
only the persisted state paths differ.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names or IDs in chat.

**Checkpoints this step drives (run each in isolation):**

| Step | Checkpoint | Gate |
|------|-----------|------|
| DA3.1 | `WD-API-CLIENT-001` — Workday API client registered (SAML ****** grant, functional areas, Include Workday Owned Scope = Yes) | attest |
| DA3.2 | `WD-API-CLIENT-001` — Workday connection fields captured with the registered API client | attest |
| DA3.3 | `WD-TENANT-001` — signed-in employee SAML authentication policy verified | attest |
| DA3.4 | `WD-CONN-102` *(reuse)* — Workday X.509 signing cert matches the Entra one | manual/attest |

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

Both `WD-API-CLIENT-001` and `WD-TENANT-001` are always `MANUAL` — they read only
`.local/connect/workday-da/config.json` and echo the captured values. A `MANUAL`
result is **never** completion: each attest row also needs the user's explicit
acknowledgement (enforced by
[`shared/checklist-updater.md`](shared/checklist-updater.md)).

**Build order.** These tasks must happen in Workday's natural order, which is
**not** the row-number order: sign-in cert (DA3.0c) → Tenant Setup – Security
(DA3.0d) → **register the API client (DA3.1 + DA3.2)** → **verify the
signed-in employee authentication policy (DA3.3)**. Each section states which
checklist row(s) it completes.

**On every resume, always re-run DA3.0 (Workday-admin gate) and DA3.0b
(single-tenant SAML pre-gate) first — both are idempotent/read-only — before
working the first incomplete row.** The SAML pre-gate is a safety check that
must run before any tenant change; skipping it on resume risks silently
overwriting an active federation. After re-running DA3.0 and DA3.0b, skip any row
whose `setupStatus` state is already `done`.

---

## DA3.0 — Workday administrator gate

Every task in this step is a **manual Workday-tenant change** — the SAML signing
certificate, Tenant Setup – Security, the Workday API client, and the
authentication policy. None is reachable through a Microsoft admin API, and the
person running this kit (the maker) is often **not** a Workday administrator. So
these steps must be performed **together with a Workday administrator**. Before
making any tenant change, confirm one is lined up.

This is the attested gate for **DA3.1** (`GATE_MODE = "attested"`, `STEP_ID =
"DA3.1"`, per [`shared/permission-gate.md`](shared/permission-gate.md)) — Workday
has **no directory the kit can query**, so it is an explicit confirmation, not a
programmatic check.

**Message:**

The next steps change your Workday tenant directly — the SAML signing
certificate, Tenant Setup – Security, the Workday API client, and the
authentication policy. These are Workday-administrator tasks, so they should be
done **together with a Workday administrator** (if that isn't you). Before we
start, please confirm you have a Workday administrator ready to work through these
steps with you.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Workday administrator",
    "question": "Have you looped in a Workday admin to perform the Workday side of configuration?",
    "options": [
      { "label": "Yes, I have" },
      { "label": "No, I have not" }
    ],
    "allowFreeformInput": false
  }
]
```

**If the user chose "Yes, I have":**
- Set `GATE_RESULT = "pass"` and
  `GATE_EVIDENCE = { "method": "attested", "outcome": "pass", "provenance": "user-attestation", "note": "user confirmed a Workday administrator is available to perform DA3.1–DA3.4 with them", "capturedAt": "<current UTC timestamp>" }`.
- Carry `GATE_EVIDENCE` forward (recorded when the DA3 rows are updated), and
  continue to DA3.0b.

**If the user chose "No, I have not":**

**Message:**

No problem — these steps have to be done with a Workday administrator. Line one up
(or ask whoever holds that role to join you), then come back and run this skill
again.

**End message.**

- Set `GATE_RESULT = "stop"` and **halt** — do not continue.

> An attested `"pass"` records that a Workday administrator was **confirmed
> available**, not directory-proven. It satisfies the *gate*, but it does **not**
> by itself complete any DA3 row — each row still needs its own captured evidence
> and acknowledgement per
> [`shared/checklist-updater.md`](shared/checklist-updater.md).

---

## DA3.0b — Single-tenant SAML pre-gate *(do this before any tenant change)*

Workday supports exactly **one** active Entra-tenant SAML federation at a time.
Pointing a second Entra tenant at the same Workday tenant silently breaks the
first. Before changing anything, identify and record the **current active SAML
IdP** so a later step never overwrites an unrelated federation.

**Message:**

Before I change any Workday security settings, I need to check the tenant's
current SAML sign-on. In Workday, search for and open the **Edit Tenant Setup –
Security** task and find the **SAML Setup** section. Tell me, for the currently
enabled Identity Provider row: the **Issuer** (or IdP name), the **Service
Provider ID**, and the **x509 Certificate** name plus its **Valid From** /
**Valid To** dates (Workday shows no thumbprint). If there is
no active SAML IdP yet, just say **none**.

**End message.**

Wait for the user's answer, then record it as the pre-gate evidence
(`SAML_ISSUER`, `SAML_SP_ID`, `SAML_CERT`).

- **If an IdP is already active AND it is not the Entra app DA-2 provisioned**
  (the Issuer / Service Provider ID does not match this tenant's `appIdUri` /
  `entraAppId` from `.local/connect/workday-da/config.json`):

  **Message:**

  This Workday tenant already has a **different** SAML identity provider active.
  Workday only allows one at a time, and replacing it would break the existing
  sign-on for its users. This V1 setup supports Microsoft Entra ID Integrated
  authentication only; direct Workday federation through Okta, Ping, or another
  provider is not supported. I'm stopping here so nothing is overwritten.
  Confirm the intended federation with the Workday and identity administrators
  before continuing.

  **End message.**

  **Halt.** Do not proceed.

- **Otherwise** (no active IdP, or the active one is this tenant's own Entra app)
  → continue.

---

## DA3.0c — Upload the X.509 signing certificate & confirm certificate parity *(completes DA3.4)*

Create the Workday **X.509 Public Key** from the Entra signing certificate DA-2
activated, then confirm the certificate matches — a mismatch means the wrong
certificate was uploaded and SSO will fail.

**Message:**

In Entra, open **Enterprise applications → your Workday app → Single sign-on →
SAML Signing Certificate**, and download the **Certificate (Base64)**. Then in
Workday, run the **Create x509 Public Key** task and paste that certificate. Type
**done** when the key is created.

**End message.**

Wait for the user, then verify the certificate parity against the certificate
DA-2 activated in Entra.

**Message:**

Now I'll compare the certificate you uploaded in Workday against the one activated
in Entra to make sure they match.

**End message.**

**Verify (WD-CONN-102):**

Read `entraAdminAccount` from `.local/connect/workday-da/config.json` as
`ENTRA_ADMIN_ACCOUNT`. If it is absent, re-run DA2.0 before this checkpoint;
do not allow an unpinned cached account to choose the Entra tenant identity.

```
python scripts/flightcheck/cli.py --checkpoint WD-CONN-102 --connect-config ".local/connect/workday-da/config.json" --preferred-username "{ENTRA_ADMIN_ACCOUNT}"
```

`WD-CONN-102` reports the Entra-side certificate health and returns `MANUAL` for
the Workday-side comparison (the Workday cert field is not API-reachable).

If FlightCheck's Microsoft Graph token has expired or the cache was cleared, this
command **opens a browser window for a Graph sign-in** before it returns. That is
expected — do **not** cancel or re-run it while it pauses; it is blocked on the
sign-in, not hung, and continues once you complete it.

**Show the `WD-CONN-102` result in chat first.** It always returns `MANUAL` for
the Workday-side comparison, so render it per
[`shared/checklist-updater.md`](shared/checklist-updater.md) §U.0–U.0a — the
result table **and** its full verification steps — **before** the
certificate-parity question below. Never ask the user to attest to a comparison
they have not been shown.

**Message:**

Workday doesn't display a certificate thumbprint, so we compare another way.
Confirm you uploaded the exact **Certificate (Base64)** from your Workday app in
Entra (Single sign-on → SAML Signing Certificate), and that the **Valid From** /
**Valid To** dates shown on the Workday x509 Public Key match that Entra
certificate's validity dates. Do they match?

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Certificate parity",
    "question": "Does the uploaded Workday certificate (and its Valid From / Valid To dates) match the Entra signing certificate?",
    "options": [
      { "label": "Yes, they match" },
      { "label": "No / not sure" }
    ],
    "allowFreeformInput": false
  }
]
```

- **"Yes, they match"** → update **DA3.4** via
  [`shared/checklist-updater.md`](shared/checklist-updater.md) with
  `STEP_ID="DA3.4"`, `GATE="manual"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true`,
  `ROW_EVIDENCE` recording the compared thumbprints and confirmation, and the
  carried `GATE_EVIDENCE`.
- **"No / not sure"** → leave DA3.4 `in-progress`; have the user re-upload the
  correct Base64 certificate from Entra and re-check. Do not continue to DA3.0d
  with a mismatched cert.

---

## DA3.0d — Edit Tenant Setup – Security

Configure the tenant's security so OAuth and SAML sign-on work. This is captured
as part of the `WD-TENANT-001` attestation (verified at the end of DA3.3).

**Message:**

In Workday, run **Edit Tenant Setup – Security**. Set the **Redirect URL** for
the sign-on, and enable both **OAuth 2.0 Clients Enabled** and **SAML**. In the
SAML Setup, confirm the **Service Provider ID** matches your Entra app's
**Identifier (Entity ID)** — they must be identical. Type **done** when saved.

**End message.**

Wait for the user, then continue to DA3.1.

---

## DA3.1 + DA3.2 — Register the API client & capture the connection fields

Register the Workday API client, then capture the connection identifiers the
Workday extension package's connection form needs.

**Message:**

In Workday, run the **Register API Client** task with **Client Grant Type = SAML
******. Under **Scope (Functional Areas)** select **Core Payroll**,
**Organizations and Roles**, **Staffing**, and **Time Off and Leave**, and set
**Include Workday Owned Scope = Yes** (this is required for the REST
`/workers/me` call). Save it, then open **View API Client** for the client you
just created. Type **done** when you're on the View API Client screen.

**End message.**

**Message:**

This setup uses each signed-in employee's Workday identity. It does **not** use
an Integration System User, a RaaS report, or an Integration System Security
Group. The functional areas above define which Workday APIs the client can call;
the employee's existing Workday security determines which employee data those
calls may return. There is no separate domain-to-integration-security-group
mapping step in this setup.

**End message.**

Wait for the user. Then **capture and validate the connection fields** using the
shared [`shared/connection-fields.md`](shared/connection-fields.md) (sections
C.1–C.6), passing whatever is already known from
`.local/connect/workday-da/config.json`:

- `OAUTH_CLIENT_ID`, `TOKEN_ENDPOINT` — from the **View API Client** screen.
- `WD_TENANT`, `WD_BASE_URL`, `WD_TOKEN_HOST` — read from
  `.local/connect/workday-da/config.json` if already captured, otherwise gathered
  here from the Workday tenant URL (the token endpoint on the View API Client
  screen has the form `https://{WD_TOKEN_HOST}/ccx/oauth2/{WD_TENANT}/token`).
- `APP_ID_URI` — the Entra `appIdUri` from DA-2.

`shared/connection-fields.md` derives the **SOAP base URL** from the Workday web
host (with a user-prompt fallback), trims the **REST base URL** to `/api`, and
persists `oauthClientId`, `tokenEndpoint`, `soapBaseUrl`, `restBaseUrl`, and
`appIdUri` back to `.local/connect/workday-da/config.json` (round-trip merge —
never drop fields owned by other steps).

**Message:**

Now I'll confirm the Workday API client you registered was captured correctly.

**End message.**

**Verify (WD-API-CLIENT-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-API-CLIENT-001 --connect-config ".local/connect/workday-da/config.json"
```

This echoes the captured `oauthClientId` / `tokenEndpoint` and restates the
registration facts to confirm. `WD-API-CLIENT-001` always returns `MANUAL`, so
render its result in chat per
[`shared/checklist-updater.md`](shared/checklist-updater.md) §U.0–U.0a — the
result table **and** its full verification steps — **before** you ask the user
to acknowledge the row. Then:

- Confirm the row via [`shared/checklist-updater.md`](shared/checklist-updater.md)
  with `STEP_ID="DA3.1"`, `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`,
  `ACK=true` once the user acknowledges the client is registered correctly,
  plus `ROW_EVIDENCE` recording the confirmed registration facts and the
  carried `GATE_EVIDENCE`.
- Then update **DA3.2** (connection fields captured) via
  [`shared/checklist-updater.md`](shared/checklist-updater.md) with
  `STEP_ID="DA3.2"`, `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true` —
  using the persisted fields as `ROW_EVIDENCE` and carrying `GATE_EVIDENCE`.

If the user says the client is wrong or fields are missing, leave DA3.1/DA3.2
`in-progress` and re-capture before continuing.

---

## DA3.3 — Verify the signed-in employee authentication policy

Verify that the Workday environment permits SAML authentication for the intended
employee population. Workday tenants vary in how authentication policies are
organized, and the policy screens may not expose an OAuth-client condition.
Never invent one, never route this signed-in employee setup through an ISU rule,
and never enable a disabled policy only to satisfy this checklist.

**Message:**

In Workday, open **Manage Authentication Policies** for the environment your
employees use. With your Workday administrator, verify that an active rule allows
**SAML** for the intended employee population.

- Do not use an ISU or integration-system security-group rule for this setup.
- Do not look for an OAuth-client restriction if this tenant's policy screen
  does not provide one.
- Preserve administrator access, employee coverage, and existing network/IP
  restrictions.
- If the current active policy already allows employee SAML sign-in, no change
  is needed.
- If a change is required, review all pending authentication-policy changes
  before activating them.

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Employee SAML policy",
    "question": "What did the Workday administrator confirm for the employee authentication policy?",
    "options": [
      {
        "label": "Existing active policy already allows employee SAML",
        "description": "No policy change or activation was needed"
      },
      {
        "label": "Reviewed policy change was activated",
        "description": "The admin preserved employee/admin access and existing network restrictions"
      },
      {
        "label": "Not confirmed yet",
        "description": "Keep this step in progress"
      }
    ],
    "allowFreeformInput": false
  }
]
```

For either confirmed option, capture the selected policy name or rule and whether
the existing configuration was reused or a reviewed change was activated. For
**Not confirmed yet**, leave DA3.3 `in-progress` and stop without blocking or
resetting completed rows.

Then verify the whole tenant configuration.

**Message:**

Now I'll confirm your Workday tenant security and authentication-policy settings
are in place.

**End message.**

**Verify (WD-TENANT-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-TENANT-001 --connect-config ".local/connect/workday-da/config.json"
```

This echoes the captured `tenant` / `restBaseUrl` / `soapBaseUrl` / `appIdUri`
and restates the Tenant Setup – Security and signed-in employee
authentication-policy facts to confirm.
`WD-TENANT-001` always returns `MANUAL`, so render its result in chat per
[`shared/checklist-updater.md`](shared/checklist-updater.md) §U.0–U.0a — the
result table **and** its full verification steps — **before** you ask the user to
confirm. Then update **DA3.3** via
[`shared/checklist-updater.md`](shared/checklist-updater.md) with
`STEP_ID="DA3.3"`, `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true` once
the user confirms one of the two supported outcomes above. Pass that selected
policy/rule and whether it was reused or activated as `ROW_EVIDENCE`, together
with the carried `GATE_EVIDENCE`.

The **functional** proof of all of this comes downstream, when the Workday
extension package's Dataverse connection authenticates successfully — not
from any standalone Workday call here. Verifying that connection end-to-end is
outside this skill's current scope; see DA-4 for what is and isn't checked.

---

## Done

When DA3.1–DA3.4 are all `done`, return control to the orchestrator (`SKILL.md`)
to resume at the next unverified row.

**Message:**

Your Workday tenant is configured — the signing certificate, Tenant Security, the
API client, and signed-in employee authentication policy are all set. Next I'll
review your Workday connection and let you know what's left.

**End message.**
