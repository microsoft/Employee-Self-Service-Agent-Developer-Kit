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

If `record-entra` reports `tenantFoundationReused: true`, do not show this
handoff and do not require the Workday administrator again. Continue at
Connections. Show only the affected Workday remediation step if a later
connection or employee test proves that the stored foundation has drifted.

When no matching foundation can be reused, identify the current federation
before rendering a detailed handoff. Do not add another availability
confirmation in this phase; the phase-boundary self-attestation already covers
it. Use `identityProviderQuestion` from the packet in one structured
`vscode_askQuestions` call. Present its options unchanged and leave the
selection unset.

This question selects a safe handoff branch. It is not evidence that the
administrator finished configuration.

- For **Microsoft Entra ID**, render **Workday Administrator Steps - Existing
  Microsoft Entra federation** and the applicable numbered handoff below.
- For **No enabled SAML row**, render **Workday Administrator Steps - New
  Microsoft Entra federation** and the greenfield handoff below.
- For **Okta**, **Ping Identity**, or **Another sign-in provider**, stop before
  showing certificate, tenant-security, or API-client changes. Explain that the
  enabled row belongs to an existing federation and must not be replaced. Ask
  the Workday and identity administrators to decide whether a separate
  Microsoft Entra row can be added safely. Do not show the completion question
  or response form. Preserve the current phase.
- For **I'm not sure**, explain that Microsoft Entra issuers commonly contain
  `login.microsoftonline.com` or `sts.windows.net`, Okta issuers commonly
  contain `okta.com`, and Ping issuers commonly contain `pingone.com`,
  `pingidentity.com`, or an organization-specific Ping host. Stop and ask the
  identity administrator to identify the enabled row; do not render either
  mutation handoff, the completion question, or the evidence form.

If the administrator becomes unavailable after a handoff is shown, pause
before the completion question and preserve the current phase.

### Existing Microsoft Entra federation handoff

1. **Protect the existing federation.** In Workday, run **Edit Tenant Setup -
   Security**, open **SAML Setup**, and locate the enabled **SAML Identity
   Providers** row whose **Used for Environments** value matches the employee
   environment being connected. Confirm that it is the intended Microsoft
   Entra row. Do not replace another provider's row.
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
   REST base URL ending exactly at `/ccx/api` and its SOAP service base URL
   ending exactly at `/ccx/service`. The tenant name is collected separately;
   do not append it to the SOAP base URL.
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

### New Microsoft Entra federation handoff

1. **Confirm the greenfield path.** In Workday, run **Edit Tenant Setup -
   Security**, open **SAML Setup**, and
   confirm there is no enabled SAML identity-provider row for the employee
   environment being connected. Do not modify a row owned by another
   federation.
2. **Install the Entra signing certificate.** In Entra, open **Enterprise
   applications -> the exact Workday application -> Single sign-on -> SAML
   Signing Certificate** and download **Certificate (Base64)**. In Workday, run
   **Create x509 Public Key**, paste that public certificate, give it a
   customer-chosen recognizable name, and save it. Never collect the
   certificate body in chat.
3. **Create the Microsoft Entra row.** Add a SAML identity-provider row for the
   employee environment. Set its Issuer to the packet's exact expected
   Microsoft Entra issuer, select the newly created public key in **X509
   Certificate**, and set **Service Provider ID** to the packet's exact Workday
   Service Provider ID. Confirm that the selected certificate dates exactly
   match the packet's verified Entra certificate dates.
4. **Configure tenant security.** Enable **OAuth 2.0 Clients Enabled** and
   **SAML**, save the tenant-security changes, and confirm that the new row is
   enabled for the intended employee environment.
5. **Register the employee API client.** Run **Register API Client**. Set
   **Client Grant Type** to **SAML Bearer**. Under **Scope (Functional Areas)**,
   select **Core Payroll**, **Organizations and Roles**, **Staffing**, and
   **Time Off and Leave**. Set **Include Workday Owned Scope** to **Yes**, then
   save.
6. **Capture non-secret connection values.** Open **View API Client** for that
   client and record the OAuth client ID and token endpoint. Record the REST
   base URL ending exactly at `/ccx/api` and the SOAP service base URL ending
   exactly at `/ccx/service`. Record the tenant name separately; do not append
   it to the SOAP base URL. Do not return a client secret, password, token,
   cookie, or certificate body.
7. **Verify employee authentication.** Open **Manage Authentication Policies**
   for the employee environment. Confirm an active rule allows **SAML** for the
   intended employees. Do not replace administrator safeguards, existing
   network restrictions, or route this user-delegated setup through an
   Integration System User rule.
8. **Confirm network readiness.** Give the REST and SOAP host names from step 6
   to the network administrator when organizational egress filtering applies.
   Record either that both hosts are allowed or that no customer-managed
   firewall change is required.
9. Record the enabled row's exact Issuer and Service Provider ID for the
   response form.

After an applicable handoff is shown, ask exactly:

**Has the Workday administrator completed every applicable task in this handoff?**

Present **Yes, the applicable tasks are complete** and **Not yet** as the
standard choices, initially unset and with custom entry disabled. **Not yet**
keeps the phase waiting and does not show the response form. Only after **Yes**
may the skill collect evidence.

If the administrator reports that the provider state changed from the branch
selected above, return to provider discovery instead of forcing the current
form.

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
    "question": "Enter the Workday SOAP service base URL ending at /ccx/service, without the tenant name."
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

Map the selected provider branch and submitted fields to the controller
response object:

- an applicable Microsoft Entra branch plus **Yes, it matches exactly** ->
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
  "soapBaseUrl": "https://{workday-host}/ccx/service",
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
