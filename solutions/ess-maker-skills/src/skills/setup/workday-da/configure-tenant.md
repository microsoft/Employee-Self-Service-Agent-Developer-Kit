<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phase 3 - Workday administrator

This phase never modifies Workday. The skill generates one handoff, validates
the administrator's non-secret response, derives deterministic endpoints, and
records evidence. All Workday tenant changes are performed by the Workday
administrator.

Generate one administrator handoff:

```powershell
python scripts/workday_connect.py workday-admin-packet
```

Show the packet once as a single ordered task list. Do not split it into
repeated confirmations or rerun manual-only FlightChecks that merely repeat
the same instructions.

If `record-entra` reports `tenantFoundationReused: true`, do not show this
handoff and do not require the Workday administrator again. Continue at
Connections. Show only the affected Workday remediation step if a later
connection or employee test proves that the stored foundation has drifted.

When no matching foundation can be reused, guide the Workday administrator
through these steps in order. Do not add another availability confirmation in
this phase; the phase-boundary self-attestation already covers it. If the
administrator becomes unavailable, present the handoff and pause before
showing the response form.

1. **Protect the existing federation.** In Workday, run **Edit Tenant Setup -
   Security** and find **SAML Setup**. In **SAML Identity Providers**, locate
   the enabled row whose **Used for Environments** value matches the employee
   environment being connected. Use `identityProviderQuestion` and
   `issuerConfirmationQuestion` from the packet to populate the corresponding
   fields in the consolidated response form below. Do not present them as
   separate questions. The domain examples are recognition clues, not proof.

   Handle the answer as follows:

   - **Microsoft Entra ID** - continue. If the administrator confirms that the
     displayed Issuer exactly matches the value shown in the form,
     record `identityProviderOutcome` as `verified-entra-issuer`; do not make
     them retype the value. If it differs, collect the exact displayed
     **Issuer** in the single response form. Do not infer a match from the
     provider choice alone.
   - **Okta**, **Ping Identity**, or **Another sign-in provider** - stop before
     changing the row. Explain that the current row belongs to an existing
     sign-in configuration and must not be replaced. Ask the Workday and
     identity administrators to decide whether a separate Microsoft Entra row
     can be added safely for this environment.
   - **No enabled SAML row** - continue with the Microsoft Entra setup below.
     After the new row is saved and enabled, ask the administrator to copy its
     exact **Issuer** value.
   - **I'm not sure** - explain that Microsoft Entra issuers commonly contain
     `login.microsoftonline.com` or `sts.windows.net`, Okta issuers commonly
     contain `okta.com`, and Ping issuers commonly contain `pingone.com`,
     `pingidentity.com`, or an organization-specific Ping host. If the value
     is still unclear, stop and ask the identity administrator rather than
     guessing.

   After the supported Microsoft Entra row is identified or created, verify
   its Issuer and Service Provider ID.
2. **Install the Entra signing certificate.** In Entra, open **Enterprise
   applications -> the exact Workday application -> Single sign-on -> SAML
   Signing Certificate** and download **Certificate (Base64)**. In Workday, run
   **Create x509 Public Key**, paste that public certificate, give it a
   customer-chosen recognizable name, and save it. Return to the enabled
   Microsoft Entra row and select that key in its **X509 Certificate** field.

   Use `certificateSelectionQuestion` and `certificateValidityQuestion` from
   the packet to populate the corresponding fields in the consolidated form.
   Do not present them separately. Never suggest, prefill, or ask the administrator to confirm
   a guessed certificate name such as “Microsoft Azure Federated SSO
   Certificate.”

   Handle the answer as follows:

   - **The new certificate created from the Entra Base64 file** - record
     `certificateSelectionOutcome` as
     `entra-signing-certificate-selected`. If both displayed dates exactly
     match the verified Entra dates shown in the form, record
     `certificateValidityOutcome` as
     `matches-verified-entra-certificate`. The customer-created certificate
     display name is optional support context, not a completion gate.
   - **A different existing Workday certificate** - stop. Do not replace or
     reuse it until the Workday and identity administrators confirm it is the
     same active Entra signing certificate.
   - **No certificate is selected** - ask the administrator to select the new
     Workday public key created from the Entra Base64 certificate, then return
     to this question.
   - **I'm not sure** - direct the administrator to the enabled Microsoft Entra
     SAML row's **X509 Certificate** field. If they still cannot identify the
     selected key, stop rather than guessing.

   Never collect the certificate body in chat.
3. **Configure tenant security.** Return to **Edit Tenant Setup - Security**.
   Enable **OAuth 2.0 Clients Enabled** and **SAML**. In SAML Setup, set the
   exact Service Provider ID to
   `http://www.workday.com/{workdayTenant}`. Do not use
   `api://{entraAppId}` in that Workday field.
4. **Register the employee API client.** Run **Register API Client**. Set
   **Client Grant Type** to **SAML Bearer**. Under **Scope (Functional Areas)**,
   select **Core Payroll**, **Organizations and Roles**, **Staffing**, and
   **Time Off and Leave**. Set **Include Workday Owned Scope** to **Yes**, then
   save.
5. **Capture non-secret connection values.** Open **View API Client** for that
   client and record the OAuth client ID and token endpoint. Record the tenant’s
   REST base URL ending exactly at `/ccx/api` and its SOAP service base URL.
   Do not return a client secret, password, token, cookie, or certificate body.
6. **Verify employee authentication.** Open **Manage Authentication Policies**
   for the employee environment. Confirm an active rule allows **SAML** for the
   intended employees. Do not replace administrator safeguards, existing
   network restrictions, or route this user-delegated setup through an
   Integration System User rule.
7. **Confirm network readiness.** Give the REST and SOAP host names from step 5
   to the network administrator when organizational egress filtering applies.
   Record either that both hosts are allowed or that no customer-managed
   firewall change is required. Do not wait until final employee validation to
   discover a known allowlist requirement.

Collect exactly one response form using one structured
`vscode_askQuestions` call. Do not collapse these fields into a multiline text
box, ask the administrator to edit a prose template, or ask for these values
as a sequence of separate chat questions:

- confirmation that the enabled issuer exactly matches the displayed verified
  Entra issuer, or the exact different Issuer value;
- enabled Service Provider ID;
- confirmation that the Entra-derived certificate is selected;
- confirmation that its displayed validity dates exactly match the verified
  Entra dates;
- optional Workday certificate display name;
- Workday OAuth client ID;
- OAuth token URL;
- REST base URL ending at `/ccx/api`;
- SOAP base URL;
- authentication-policy outcome;
- network-readiness outcome.

Use this exact form, substituting the packet's expected issuer, Service
Provider ID, and verified certificate dates:

```json
[
  {
    "header": "Identity provider",
    "question": "Which sign-in provider does the enabled Workday SAML row use?",
    "options": [
      { "label": "Microsoft Entra ID", "description": "Issuer commonly contains login.microsoftonline.com or sts.windows.net" },
      { "label": "Okta", "description": "Issuer commonly contains okta.com" },
      { "label": "Ping Identity", "description": "Issuer commonly contains pingone.com, pingidentity.com, or an organization-specific Ping host" },
      { "label": "Another sign-in provider" },
      { "label": "No enabled SAML row" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Issuer",
    "question": "Does the enabled Microsoft Entra SAML row's Issuer exactly match {EXPECTED_ENTRA_ISSUER}?",
    "options": [
      { "label": "Yes, it matches exactly" },
      { "label": "No, the displayed Issuer is different" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Different issuer",
    "question": "If the Issuer is different, enter the exact displayed value. Otherwise leave this blank."
  },
  {
    "header": "Service Provider ID",
    "question": "Enter the enabled Service Provider ID. Expected value: {EXPECTED_SERVICE_PROVIDER_ID}"
  },
  {
    "header": "Certificate",
    "question": "Which certificate is selected on the enabled Microsoft Entra SAML row in Workday?",
    "options": [
      { "label": "The new certificate created from the Entra Base64 file" },
      { "label": "A different existing Workday certificate" },
      { "label": "No certificate is selected" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Certificate dates",
    "question": "Do the selected Workday certificate dates exactly match {CERTIFICATE_VALID_FROM} through {CERTIFICATE_VALID_TO}?",
    "options": [
      { "label": "Yes, both dates match exactly" },
      { "label": "No, one or both dates are different" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Certificate name",
    "question": "Optional: enter the Workday certificate display name, or leave this blank."
  },
  {
    "header": "OAuth client ID",
    "question": "Enter the non-secret OAuth client ID shown by Workday."
  },
  {
    "header": "OAuth token URL",
    "question": "Enter the OAuth token URL shown by Workday."
  },
  {
    "header": "REST base URL",
    "question": "Enter the Workday REST base URL ending at /ccx/api."
  },
  {
    "header": "SOAP base URL",
    "question": "Enter the Workday SOAP service base URL."
  },
  {
    "header": "Authentication policy",
    "question": "What did the administrator verify for the employee authentication policy?",
    "options": [
      { "label": "An existing active policy allows SAML" },
      { "label": "A reviewed policy was activated" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Network readiness",
    "question": "What did the administrator verify for the Workday service hosts?",
    "options": [
      { "label": "Both Workday hosts are allowed" },
      { "label": "No customer-managed firewall change is required" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave every field and option initially unset. Do not add `recommended`,
`default`, suggested-answer wording, or any equivalent preselection. The
expected values in the question text are comparison references, not answers.

Map the submitted fields to the controller response object:

- **Microsoft Entra ID** plus **Yes, it matches exactly** ->
  `identityProviderOutcome: verified-entra-issuer`;
- a different Issuer -> `activeIdentityProviderIssuer`, then stop for identity
  administrator review instead of submitting successful evidence;
- **The new certificate created from the Entra Base64 file** ->
  `certificateSelectionOutcome: entra-signing-certificate-selected`;
- matching certificate dates ->
  `certificateValidityOutcome: matches-verified-entra-certificate`;
- the optional display name -> `certificateName`;
- the six entered connection/policy fields -> their corresponding controller
  keys;
- existing active policy -> `existing-active-policy`;
- reviewed and activated policy -> `reviewed-policy-activated`;
- both hosts allowed -> `confirmed-hosts-allowed`;
- no firewall change required ->
  `no-customer-firewall-change-required`.

Any unsupported provider, mismatch, missing certificate, date mismatch, or
**I'm not sure** answer is a remediation outcome, not successful evidence.
Show the affected remediation step and keep the phase waiting.

If the administrator omits a required value or replies only with wording such
as "done", "all good", "continue", or "proceed", do not move to another field,
search workspace files, inspect environment variables, or infer the missing
evidence. Reopen the same structured form with only the missing or invalid
fields; never replace it with a free-text request for several numbered answers.
Preserve progress and stop until the structured form is complete.

Never collect a secret, password, token, cookie, certificate body, or private
key. Write the response directly to
`.local/connect/workday-da/workday-admin-response.json` using a structured
file-write tool; never interpolate administrator-entered values into a
generated shell command. Pass the response once:

```powershell
python scripts/workday_connect.py record-workday-admin --response-file ".local\connect\workday-da\workday-admin-response.json"
```

Use these exact outcome values:

- `authenticationPolicyOutcome`: `existing-active-policy` or
  `reviewed-policy-activated`;
- `networkReadinessOutcome`: `confirmed-hosts-allowed` or
  `no-customer-firewall-change-required`.

For example:

```json
{
  "identityProviderOutcome": "verified-entra-issuer",
  "enabledServiceProviderId": "http://www.workday.com/{workdayTenant}",
  "certificateSelectionOutcome": "entra-signing-certificate-selected",
  "certificateValidityOutcome": "matches-verified-entra-certificate",
  "oauthClientId": "{non-secret Workday OAuth client ID}",
  "oauthTokenUrl": "https://{workday-host}/ccx/oauth2/{tenant}/token",
  "restBaseUrl": "https://{workday-host}/ccx/api",
  "soapBaseUrl": "https://{workday-host}/ccx/service/{tenant}",
  "authenticationPolicyOutcome": "existing-active-policy",
  "networkReadinessOutcome": "confirmed-hosts-allowed"
}
```

The controller validates the verified Entra issuer, Service Provider ID, HTTPS
endpoints, exact REST base suffix, certificate selection, and certificate-date
match before recording the non-secret identifiers, endpoints, and evidence
atomically. It captures the completed Entra and Workday phases as a tenant
foundation that can be reused for another environment or ESS HR agent. If the
administrator is not available, stop here; rerun
`workday-admin-packet` later without losing deployment progress.
