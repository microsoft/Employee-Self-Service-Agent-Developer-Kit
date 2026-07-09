<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Skill 4 — Configure the Workday Tenant

Role: **Workday Administrator**. This skill performs the Workday-tenant-side
configuration the simplified setup requires: the SAML X.509 signing certificate,
Tenant Setup – Security, the Workday API client, and the authentication policy.
It owns master-checklist rows **S4.1 through S4.4**.

Depends on skill 3 (the Entra app must already exist — this skill reads its
`entraAppId` / `appIdUri` and the activated signing-cert thumbprint). It is
**Workday-only**: none of these tasks is reachable through a Microsoft admin API,
and standing up a Workday connection to self-verify would be **circular** (it
needs the same Entra-app + tenant configuration the ESS agent itself needs). So
every step here is a **manual Workday-admin task**, and its flightcheck reports
`MANUAL` — it echoes what the operator captured and names the Workday screen to
verify, but it never marks a row done on its own.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not rephrase, add commentary, or tell the user what tools you are calling or what
files you are reading. **Never** show internal variable names or IDs in chat.

**Checkpoints this skill drives (run each in isolation):**

| Step | Checkpoint | Gate |
|------|-----------|------|
| S4.1 | `WD-API-CLIENT-001` — Workday API client registered (SAML ****** grant, functional areas, Include Workday Owned Scope = Yes) | attest |
| S4.2 | `WD-TENANT-001` — Tenant Setup – Security + connection fields captured | attest |
| S4.3 | `WD-TENANT-001` — authentication policy scoped to the OAuth client + activated | attest |
| S4.4 | `WD-CONN-102` *(reuse)* — Workday X.509 signing-cert thumbprint matches the Entra one | manual/attest |

Run any one with:

```
python scripts/flightcheck/cli.py --checkpoint <ID>
```

Both `WD-API-CLIENT-001` and `WD-TENANT-001` are always `MANUAL` — they read only
`.local/connect/workday/config.json` and echo the captured values. A `MANUAL`
result is **never** completion: each attest row also needs the user's explicit
acknowledgement (enforced by [`shared/checklist-updater.md`](../shared/checklist-updater.md)).

**Build order.** These tasks must happen in Workday's natural order, which is
**not** the row-number order: sign-in cert (P4.1) → Tenant Setup – Security
(P4.2) → **register the API client (P4.3)** → **authentication policy (P4.4)**.
The API client is registered **before** the authentication policy because the
policy must be scoped to the OAuth client identity, which only exists once the
client is registered. Each section states which checklist row(s) it completes.

**On every resume, always re-run P4.0 (Workday-admin gate) and P4.0b (single-tenant SAML
pre-gate) first — both are idempotent/read-only — before working the first
incomplete row.** The SAML pre-gate is a safety check that must run before any
tenant change; skipping it on resume risks silently overwriting an active
federation. After re-running P4.0 and P4.0b, skip any row whose `setupStatus`
state is already `done`.

---

## P4.0 — Workday administrator gate

Every task in this skill is a **manual Workday-tenant change** — the SAML signing
certificate, Tenant Setup – Security, the Workday API client, and the
authentication policy. None is reachable through a Microsoft admin API, and the
person running this kit (the maker) is often **not** a Workday administrator. So
these steps must be performed **together with a Workday administrator**. Before
making any tenant change, confirm one is lined up.

This is the attested gate for **S4.1** (`GATE_MODE = "attested"`, `STEP_ID =
"S4.1"`, per [`permission-gate.md`](../shared/permission-gate.md)) — Workday has
**no directory the kit can query**, so it is an explicit confirmation, not a
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
    "question": "Have you provisioned a Workday administrator to perform these manual Workday configuration steps with you?",
    "options": [
      { "label": "Yes, I have", "recommended": true },
      { "label": "No, I have not" }
    ],
    "allowFreeformInput": false
  }
]
```

**If the user chose "Yes, I have":**
- Set `GATE_RESULT = "pass"` and
  `GATE_EVIDENCE = { "verifiedBy": "attested", "note": "user confirmed a Workday administrator is available to perform S4.1–S4.4 with them" }`.
- Carry `GATE_EVIDENCE` forward (recorded when the S4 rows are updated), and
  continue to P4.0b.

**If the user chose "No, I have not":**

**Message:**

No problem — these steps have to be done with a Workday administrator. Line one up
(or ask whoever holds that role to join you), then come back and run this skill
again.

**End message.**

- Set `GATE_RESULT = "stop"` and **halt** — do not continue.

> An attested `"pass"` records that a Workday administrator was **confirmed
> available**, not directory-proven. It satisfies the *gate*, but it does **not**
> by itself complete any S4 row — each row still needs its own captured evidence
> and acknowledgement per [`checklist-updater.md`](../shared/checklist-updater.md).

---

## P4.0b — Single-tenant SAML pre-gate *(do this before any tenant change)*

Workday supports exactly **one** active Entra-tenant SAML federation at a time.
Pointing a second Entra tenant at the same Workday tenant silently breaks the
first. Before changing anything, identify and record the **current active SAML
IdP** so a later step never overwrites an unrelated federation.

**Message:**

Before I change any Workday security settings, I need to check the tenant's
current SAML sign-on. In Workday, search for and open the **Edit Tenant Setup –
Security** task and find the **SAML Setup** section. Tell me, for the currently
enabled Identity Provider row: the **Issuer** (or IdP name), the **Service
Provider ID**, and the **x509 Certificate** name/thumbprint in use. If there is
no active SAML IdP yet, just say **none**.

**End message.**

Wait for the user's answer, then record it as the pre-gate evidence
(`SAML_ISSUER`, `SAML_SP_ID`, `SAML_CERT`).

- **If an IdP is already active AND it is not the Entra app skill-3 provisioned**
  (the Issuer / Service Provider ID does not match this tenant's `appIdUri` /
  `entraAppId` from `.local/connect/workday/config.json`):

  **Message:**

  This Workday tenant already has a **different** SAML identity provider active.
  Workday only allows one at a time, and replacing it would break the existing
  sign-on for its users. I'm stopping here so nothing is overwritten — please
  confirm with whoever owns that federation before continuing, then come back.

  **End message.**

  **Halt.** Do not proceed.

- **Otherwise** (no active IdP, or the active one is this tenant's own Entra app)
  → continue.

---

## P4.1 — Upload the X.509 signing certificate & confirm thumbprint parity *(completes S4.4)*

Create the Workday **X.509 Public Key** from the Entra signing certificate skill-3
activated, then confirm the thumbprint matches — a mismatch means the wrong
certificate was uploaded and SSO will fail.

**Message:**

In Entra, open **Enterprise applications → your Workday app → Single sign-on →
SAML Signing Certificate**, and download the **Certificate (Base64)**. Then in
Workday, run the **Create x509 Public Key** task and paste that certificate. Type
**done** when the key is created.

**End message.**

Wait for the user, then verify the thumbprint parity against the certificate
skill-3 activated in Entra.

**Message:**

Now I'll compare the certificate you uploaded in Workday against the one activated
in Entra to make sure they match.

**End message.**

**Verify (WD-CONN-102):**

```
python scripts/flightcheck/cli.py --checkpoint WD-CONN-102
```

`WD-CONN-102` reports the Entra-side certificate health and returns `MANUAL` for
the Workday-side comparison (the Workday cert field is not API-reachable).

If FlightCheck's Microsoft Graph token has expired or the cache was cleared, this
command **opens a browser window for a Graph sign-in** before it returns. That is
expected — do **not** cancel or re-run it while it pauses; it is blocked on the
sign-in, not hung, and continues once you complete it.

**Message:**

Does the certificate thumbprint you uploaded in Workday match the one shown for
your Workday app in Entra (Single sign-on → SAML Signing Certificate →
Thumbprint)?

**End message.**

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Certificate thumbprint",
    "question": "Do the Workday and Entra signing-certificate thumbprints match?",
    "options": [
      { "label": "Yes, they match", "recommended": true },
      { "label": "No / not sure" }
    ],
    "allowFreeformInput": false
  }
]
```

- **"Yes, they match"** → update **S4.4** via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S4.4"`,
  `GATE="manual"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true`.
- **"No / not sure"** → leave S4.4 `in-progress`; have the user re-upload the
  correct Base64 certificate from Entra and re-check. Do not continue to P4.2 with
  a mismatched cert.

---

## P4.2 — Edit Tenant Setup – Security

Configure the tenant's security so OAuth and SAML sign-on work. This is captured
as part of the `WD-TENANT-001` attestation (verified at the end of P4.4).

**Message:**

In Workday, run **Edit Tenant Setup – Security**. Set the **Redirect URL** for
the sign-on, and enable both **OAuth 2.0 Clients Enabled** and **SAML**. In the
SAML Setup, confirm the **Service Provider ID** matches your Entra app's
**Identifier (Entity ID)** — they must be identical. Type **done** when saved.

**End message.**

Wait for the user, then continue to P4.3.

---

## P4.3 — Register the API client & capture the connection fields *(completes S4.1 + S4.2)*

Register the Workday API client, then capture the connection identifiers skill-5
will consume. **Register the client before touching the authentication policy
(P4.4)** — the policy is scoped to this client's identity.

**Message:**

In Workday, run the **Register API Client** task with **Client Grant Type = SAML
******. Under **Scope (Functional Areas)** select **Core Payroll**,
**Organizations and Roles**, **Staffing**, and **Time Off and Leave**, and set
**Include Workday Owned Scope = Yes** (this is required for the REST
`/workers/me` call). Save it, then open **View API Client** for the client you
just created. Type **done** when you're on the View API Client screen.

**End message.**

Wait for the user. Then **capture and validate the connection fields** using the
shared [`connection-fields.md`](../shared/connection-fields.md) (sections C.1–C.6),
passing whatever is already known from
`.local/connect/workday/config.json`:

- `OAUTH_CLIENT_ID`, `TOKEN_ENDPOINT` — from the **View API Client** screen.
- `WD_TENANT`, `WD_BASE_URL`, `WD_TOKEN_HOST` — read from
  `.local/connect/workday/config.json` if already captured, otherwise gathered
  here from the Workday tenant URL (the token endpoint on the View API Client
  screen has the form `https://{WD_TOKEN_HOST}/ccx/oauth2/{WD_TENANT}/token`).
- `APP_ID_URI` — the Entra `appIdUri` from skill-3.

`connection-fields.md` derives the **SOAP base URL** from the Workday web host
(with a user-prompt fallback), trims the **REST base URL** to `/api`, and persists
`oauthClientId`, `tokenEndpoint`, `soapBaseUrl`, `restBaseUrl`, and `appIdUri`
back to `.local/connect/workday/config.json` (round-trip merge — never drop
fields owned by other steps).

**Message:**

Now I'll confirm the Workday API client you registered was captured correctly.

**End message.**

**Verify (WD-API-CLIENT-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-API-CLIENT-001
```

This echoes the captured `oauthClientId` / `tokenEndpoint` and restates the
registration facts to confirm. Show the user the checkpoint's result, then:

- Confirm the row via [`checklist-updater.md`](../shared/checklist-updater.md)
  with `STEP_ID="S4.1"`, `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true`
  once the user acknowledges the client is registered correctly.
- Then update **S4.2** (connection fields captured) via
  [`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S4.2"`,
  `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true` — using the persisted
  fields as the captured evidence.

If the user says the client is wrong or fields are missing, leave S4.1/S4.2
`in-progress` and re-capture before continuing.

---

## P4.4 — Scope & activate the authentication policy *(completes S4.3)*

Scope the authentication policy to the OAuth client from P4.3 and activate it.

**Message:**

In Workday, run **Manage Authentication Policies**. Add or edit the policy so it
is scoped to the **OAuth client you registered in the previous step**, and allow
**SAML** as an allowed authentication type. Then run **Activate All Pending
Authentication Policy Changes** to make it live. Type **done** when the changes
are activated.

**End message.**

Wait for the user, then verify the whole tenant configuration.

**Message:**

Now I'll confirm your Workday tenant security and authentication-policy settings
are in place.

**End message.**

**Verify (WD-TENANT-001):**

```
python scripts/flightcheck/cli.py --checkpoint WD-TENANT-001
```

This echoes the captured `tenant` / `restBaseUrl` / `soapBaseUrl` / `appIdUri` and
restates the Tenant Setup – Security and authentication-policy facts to confirm.
Show the user the result, then update **S4.3** via
[`checklist-updater.md`](../shared/checklist-updater.md) with `STEP_ID="S4.3"`,
`GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true` once the user confirms
the policy is scoped and activated.

The **functional** proof of all of this comes downstream, when skill-5's Copilot
Studio connection authenticates successfully — not from any standalone Workday
call here.

---

## Done

When S4.1–S4.4 are all `done`, return control to the setup router (`SKILL.md`) to
resume at the next unverified row.

**Message:**

Your Workday tenant is configured — the signing certificate, Tenant Security, the
API client, and the authentication policy are all set. Next up is installing the
Workday extension pack and binding the connection.

**End message.**
