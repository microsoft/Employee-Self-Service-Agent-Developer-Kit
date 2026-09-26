<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-3 — Complete the Workday Administrator Handoff

Role: **Workday Administrator**. This phase covers the Workday-side changes
required by the signed-in employee connection:

- trust the Microsoft Entra signing certificate;
- configure Tenant Setup – Security;
- register the Workday API client and capture its connection values; and
- confirm an active employee authentication policy allows SAML.

It owns internal rows **DA3.1 through DA3.4**, but presents them to the
customer as one **Workday administrator** milestone. Do not expose internal row
IDs or checkpoint IDs.

The skill cannot sign in to the Workday administration interface, cannot
change these settings through a Microsoft API, and must never request or
collect a Workday administrator's password. The administrator performs the
steps using their normal organization-approved Workday account.

Every **Message** block is exact customer text. Do not add internal variables,
file paths, checkpoint output, or implementation commentary.

On resume, always repeat the administrator availability and active-federation
safety checks before presenting any unfinished Workday action. Skip individual
actions already supported by current scoped evidence, but present the
remaining actions as one handoff rather than separate lifecycle rows.

---

## DA3.0 — Confirm the administrator is available

**Message:**

The next milestone requires a Workday administrator. They will use their normal
Workday access to configure sign-in trust, tenant security, the API client, and
the employee authentication policy. The skill will not sign in to Workday or
ask for their password.

**End message.**

Use `vscode_askQuestions`:

```json
[
  {
    "header": "Workday administrator",
    "question": "Is a Workday administrator available to complete the Workday-side setup now?",
    "options": [
      { "label": "Yes, continue" },
      { "label": "Not yet" }
    ],
    "allowFreeformInput": false
  }
]
```

If the answer is **Not yet**, pause without changing Workday state. If the
answer is **Yes, continue**, record an attested administrator-availability
gate and continue.

---

## DA3.0b — Protect the active federation

Workday supports one active SAML identity provider. Before presenting any
tenant change, require the administrator to classify the current configuration.

**Message:**

Before changing Workday sign-in, have the administrator open **Edit Tenant
Setup – Security**, find **SAML Setup**, and choose the description that
applies:

1. **No Identity Provider is enabled.**
2. **The Microsoft Entra provider intended for this setup is enabled.** Provide
   only its **Service Provider ID**.
3. **A different provider is enabled, or the administrator is not sure.**

Reply with **1**, **2** plus the Service Provider ID, or **3**.

**End message.**

Record the classification and `SAML_SP_ID` when option 2 is selected. Do not
request certificate names or validity dates here, and do not ask a second
question that repeats the classification or Service Provider ID.

- **Option 1** — continue.
- **Option 2 with an exact match to this setup's `appIdUri`** — continue.
- **Option 2 without an exact match, option 3, an unclear answer, or a request
  to skip the classification** — pause the standard setup.

For the paused case, show:

**Message:**

This Workday tenant may already use a different SAML federation. Replacing the
active provider can interrupt employee sign-in, so `/connect workday` will not
perform or guide that replacement.

Have the Workday and identity administrators review the existing federation,
capture its rollback configuration, and complete any approved identity-provider
change through your organization's normal change process. After the intended
Microsoft Entra provider is active, run `/connect workday` again and choose
option 2 with its Service Provider ID.

**End message.**

Stop without presenting the remaining Workday changes.

---

## DA3.1–DA3.4 — Workday administrator work packet

Present the remaining Workday work as one packet. Values in braces come from
the Microsoft Entra phase and current provider state.

**Message:**

Complete this Workday administrator checklist:

### 1. Trust the Microsoft Entra signing certificate

1. In Microsoft Entra, open the selected Workday enterprise application.
2. Go to **Single sign-on → SAML Signing Certificate** and download
   **Certificate (Base64)**.
3. In Workday, run **Create x509 Public Key** and create the key from that
   certificate.
4. Confirm the Workday key's **Valid From** and **Valid To** dates match the
   certificate in Microsoft Entra.

### 2. Configure Tenant Setup – Security

In **Edit Tenant Setup – Security**:

1. Configure the sign-on redirect using the selected Workday application's
   Microsoft Entra SAML sign-in values.
2. Enable **OAuth 2.0 Clients Enabled**.
3. Enable **SAML**.
4. Confirm the SAML **Service Provider ID** is exactly `{APP_ID_URI}`.
5. Save the changes.

### 3. Register the Workday API client

Run **Register API Client** with:

- **Client Grant Type:** SAML ******
- **Scope (Functional Areas):** Core Payroll, Organizations and Roles,
  Staffing, and Time Off and Leave
- **Include Workday Owned Scope:** Yes

Save the client, open **View API Client**, and keep its **Client ID** and
**Token Endpoint** available.

This setup uses the signed-in employee's Workday identity. It does not require
an Integration System User, RaaS report, or Integration System Security Group.

### 4. Confirm employee SAML access

Open **Manage Authentication Policies** and verify an active rule allows
**SAML** for the intended employee population.

- Preserve administrator access and existing network or IP restrictions.
- Do not use an ISU or integration-system security-group rule.
- If the active policy already permits employee SAML, do not change it.
- If a change is necessary, review all pending policy changes before
  activation.

Return here when the checklist is complete.

**End message.**

Use one structured `vscode_askQuestions` form:

```json
[
  {
    "header": "Signing certificate",
    "question": "Does the Workday x509 key use the exact Microsoft Entra Certificate (Base64), with matching Valid From and Valid To dates?",
    "options": [
      { "label": "Yes, they match" },
      { "label": "Not complete or not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Tenant security",
    "question": "Were Tenant Setup – Security changes saved with SAML, OAuth 2.0 clients, and the matching Service Provider ID?",
    "options": [
      { "label": "Yes, saved and verified" },
      { "label": "Not complete or not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "API client ID",
    "question": "Enter the Workday API Client ID shown on View API Client.",
    "allowFreeformInput": true
  },
  {
    "header": "Token endpoint",
    "question": "Enter the Token Endpoint shown on View API Client.",
    "allowFreeformInput": true
  },
  {
    "header": "Employee SAML policy",
    "question": "What did the Workday administrator confirm?",
    "options": [
      {
        "label": "Existing active policy already allows employee SAML",
        "description": "No policy activation was required"
      },
      {
        "label": "Reviewed policy change was activated",
        "description": "Employee and administrator access were preserved"
      },
      {
        "label": "Not complete or not sure"
      }
    ],
    "allowFreeformInput": false
  }
]
```

If either confirmation is incomplete, either returned value is empty, or the
policy is not confirmed, keep the milestone in progress and show only the
unfinished checklist section on resume.

Validate and persist the connection values through
[`shared/connection-fields.md`](shared/connection-fields.md), sections C.1–C.6.
Pass the returned API client ID and token endpoint plus any previously captured
tenant and URL values. That helper validates the Workday URL shapes, derives
the SOAP and REST base URLs, requests only genuinely missing non-secret
values, and round-trip merges the provider config.

Do not run manual-only FlightCheck checkpoints merely to echo these values.
Record completion directly through
[`shared/checklist-updater.md`](shared/checklist-updater.md):

- **DA3.1** — `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true`;
  evidence records the API client grant type, functional areas, and Workday
  owned scope confirmation.
- **DA3.2** — `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true`;
  evidence records the validated client ID, token endpoint, tenant, REST base
  URL, and SOAP base URL.
- **DA3.3** — `GATE="attest"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true`;
  evidence records whether the existing policy was reused or a reviewed change
  was activated.
- **DA3.4** — `GATE="manual"`, `CHECKPOINT_RESULT="MANUAL"`, `ACK=true`;
  evidence records that the exact Entra Base64 certificate was used and its
  validity dates matched.

Use `RESULT_SOURCE="user-acknowledgement"` for all four updates and carry the
administrator-availability and federation-match gate evidence. Never store a
Workday password, employee identifier, certificate body, or returned employee
data.

---

## Done

When all four internal rows are complete, show:

**Message:**

The Workday administrator milestone is complete. The certificate, tenant
security, API client, connection values, and employee SAML policy are ready.

**End message.**

Return to the orchestrator.
