<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phase 3 - Workday administrator

This phase never modifies Workday. The skill generates one handoff, validates
the administrator's non-secret response, derives deterministic endpoints, and
records evidence. All Workday tenant changes are performed by the Workday
administrator.

Generate one administrator handoff:

```powershell
python scripts/workday_connect.py administrator-stage --phase workday-admin --substage administrator-engaged
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
  Do not infer a match from the
     provider choice alone; the administrator must confirm the displayed
  Issuer exactly matches the verified Entra issuer.
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

Record that the handoff is waiting for the administrator:

```powershell
python scripts/workday_connect.py administrator-stage --phase workday-admin --substage awaiting-completion
```

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
   `api://{entraAppId}` in that Workday field. Set the identity-provider SSO
   service URL to the packet's exact **Login URL** and the sign-on redirect URL
   to the packet's exact **Reply URL**.
4. **Reuse or register the employee API client.** First inspect the approved
   signed-in employee API client, if one exists. Reuse it only when its client
   **Client Grant Type** is **SAML Bearer**, its functional areas are exactly **Core
   Payroll**, **Organizations and Roles**, **Staffing**, and **Time Off and
   Leave**, and **Include Workday Owned Scope** is **Yes**. Otherwise run
   **Register API Client** with those exact settings. Preserve unrelated
   approved clients.
5. **Configure employee domain security separately from API scopes.** Choose
   whether this rollout covers the entire workforce or a limited/test
   population. Select the intended employee security group; for a limited/test
   rollout, never default to All Employees. Grant **Get** on
   **Worker Data: Public Worker Reports** and **Integration Permissions**.
   Do not treat the functional-area scopes from step 4 as domain permissions.
   Add another domain only when it is tied to a named supported scenario.
   Do not return employee membership lists.
6. **Capture non-secret connection values.** Open **View API Client** for that
   client and record the OAuth client ID and token endpoint. Record the tenant’s
   REST base URL ending exactly at `/ccx/api` and its SOAP service base URL
   ending exactly at `/ccx/service`. The tenant name is collected separately;
   do not append it to the SOAP base URL.
   Do not return a client secret, password, token, cookie, or certificate body.
7. **Verify employee authentication.** Open **Manage Authentication Policies**
   for the employee environment. Confirm an active rule allows **SAML** for the
   intended employees. Do not replace administrator safeguards, existing
   network restrictions, or route this user-delegated setup through an
   Integration System User rule. If a policy change is required, review every
   pending authentication-policy change, then run **Activate All Pending
   Authentication Policy Changes** before reporting the policy as activated.
8. **Confirm network readiness.** Give the REST and SOAP host names from step 6
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
   Service Provider ID. Set the identity-provider SSO service URL to the
   packet's exact **Login URL** and the sign-on redirect URL to the packet's
   exact **Reply URL**. Confirm that the selected certificate dates exactly
   match the packet's verified Entra certificate dates.
4. **Configure tenant security.** Enable **OAuth 2.0 Clients Enabled** and
   **SAML**, save the tenant-security changes, and confirm that the new row is
   enabled for the intended employee environment.
5. **Reuse or register the employee API client.** Reuse an approved signed-in
   employee API client only when it already has **SAML Bearer**, exactly the
   four required functional areas, and **Include Workday Owned Scope** set to
   **Yes**. Otherwise register a new client with those exact settings.
6. **Configure employee domain security separately from API scopes.** Choose
   the entire-workforce or limited/test rollout, select the intended employee
   security group, and grant **Get** on **Worker Data: Public Worker Reports**
   and **Integration Permissions**. Never default a limited/test rollout to All
   Employees. Add optional domains only for a named supported scenario.
7. **Capture non-secret connection values.** Open **View API Client** for that
   client and record the OAuth client ID and token endpoint. Record the REST
   base URL ending exactly at `/ccx/api` and the SOAP service base URL ending
   exactly at `/ccx/service`. Record the tenant name separately; do not append
   it to the SOAP base URL. Do not return a client secret, password, token,
   cookie, or certificate body.
8. **Verify employee authentication.** Open **Manage Authentication Policies**
   for the employee environment. Confirm an active rule allows **SAML** for the
   intended employees. Do not replace administrator safeguards, existing
   network restrictions, or route this user-delegated setup through an
   Integration System User rule. If a change is required, review every pending
   authentication-policy change and run **Activate All Pending Authentication
   Policy Changes** before reporting the policy as activated.
9. **Confirm network readiness.** Give the REST and SOAP host names from step 7
   to the network administrator when organizational egress filtering applies.
   Record either that both hosts are allowed or that no customer-managed
   firewall change is required.
10. Record the enabled row's exact Issuer and Service Provider ID for the
   response form.

After an applicable handoff is shown, ask exactly:

**Has the Workday administrator completed every applicable task in this handoff?**

Present **Yes, the applicable tasks are complete** and **Not yet** as the
standard choices, initially unset and with custom entry disabled. **Not yet**
keeps the phase waiting and does not show the response form. Only after **Yes**
may the skill collect evidence.

After **Yes**, record the explicit completion boundary:

```powershell
python scripts/workday_connect.py administrator-stage --phase workday-admin --substage completion-confirmed
```

If the administrator reports that the provider state changed from the branch
selected above, return to provider discovery instead of forcing the current
form.

Collect exactly one response form using one structured
`vscode_askQuestions` call. Do not collapse these fields into a multiline text
box, ask the administrator to edit a prose template, or ask for these values
as a sequence of separate chat questions. This avoids repeated confirmations
while retaining all required evidence:

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
- whether an approved existing API client was verified or a new one was
  registered;
- exact client grant type and Include Workday Owned Scope outcome;
- the Workday identity-provider SSO service URL and sign-on redirect URL;
- rollout type: entire workforce or limited/test;
- selected employee security-group identity, without membership data;
- `Worker Data: Public Worker Reports` Get-permission outcome;
- `Integration Permissions > Get` outcome;
- exact API functional-area scopes;
- optional domains paired with their named supported scenarios;
- authorization outcome, including whether a bounded `Task not authorized`
  remediation was required; when it was, the affected domain, named scenario,
  and successful retest outcome.

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
    "header": "API client",
    "question": "How was the approved signed-in employee API client established?",
    "options": [
      { "label": "An existing approved client was verified" },
      { "label": "A new client was registered" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Client grant type",
    "question": "What client grant type is configured?",
    "options": [
      { "label": "SAML Bearer" },
      { "label": "Another grant type or not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Workday owned scope",
    "question": "Is Include Workday Owned Scope set to Yes?",
    "options": [
      { "label": "Yes" },
      { "label": "No or not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "SSO service URL",
    "question": "Enter the identity-provider SSO service URL. Expected value: {EXPECTED_ENTRA_LOGIN_URL}"
  },
  {
    "header": "Sign-on redirect URL",
    "question": "Enter the sign-on redirect URL. Expected value: {EXPECTED_ENTRA_REPLY_URL}"
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
  },
  {
    "header": "Rollout",
    "question": "Which employee population is this Workday rollout configured for?",
    "options": [
      { "label": "Entire workforce" },
      { "label": "Limited or test population" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Employee security group",
    "question": "Enter the selected Workday employee security-group name. Do not enter membership data."
  },
  {
    "header": "Public worker reports",
    "question": "Was Get permission verified for Worker Data: Public Worker Reports?",
    "options": [
      { "label": "Yes, Get permission is verified" },
      { "label": "No or not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Integration permissions",
    "question": "Was Get permission verified under Integration Permissions?",
    "options": [
      { "label": "Yes, Get permission is verified" },
      { "label": "No or not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Functional-area scopes",
    "question": "Enter a JSON string array containing exactly: Core Payroll, Organizations and Roles, Staffing, and Time Off and Leave. Example: [\"Core Payroll\",\"Organizations and Roles\",\"Staffing\",\"Time Off and Leave\"]"
  },
  {
    "header": "Optional domains",
    "question": "Enter a JSON array of {\"domain\":\"...\",\"scenario\":\"...\"} objects, or [] when none are required."
  },
  {
    "header": "Authorization",
    "question": "What was the final authorization result after the employee security changes?",
    "options": [
      { "label": "Verified without an authorization error" },
      { "label": "Task not authorized was remediated and retested" },
      { "label": "Task not authorized is unresolved" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Remediated domain",
    "question": "Only when Task not authorized was remediated: enter the affected domain. Otherwise leave blank."
  },
  {
    "header": "Remediation scenario",
    "question": "Only when Task not authorized was remediated: enter the named supported scenario. Otherwise leave blank."
  },
  {
    "header": "Authorization retest",
    "question": "Only when Task not authorized was remediated: was the same scenario retested successfully?",
    "options": [
      { "label": "Verified after remediation" },
      { "label": "Not retested or still failing" }
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
- approved existing client -> `apiClientOutcome:
  existing-client-verified`;
- newly registered client -> `apiClientOutcome: new-client-registered`;
- **SAML Bearer** -> `clientGrantType: saml-bearer`;
- **Yes** for Workday owned scope -> `includeWorkdayOwnedScope: yes`;
- the SSO service and sign-on redirect values ->
  `identityProviderSsoServiceUrl` and `signOnRedirectUrl`;
- the entered connection/policy fields -> their corresponding controller
  keys;
- existing active policy -> `existing-active-policy`;
- reviewed and activated policy -> `reviewed-policy-activated`;
- both hosts allowed -> `confirmed-hosts-allowed`;
- no firewall change required ->
  `no-customer-firewall-change-required`.
- entire workforce -> `rolloutType: entire-workforce`;
- limited/test population -> `rolloutType: limited-or-test`;
- selected group -> `employeeSecurityGroup`;
- each verified domain permission ->
  `get-permission-verified`;
- functional-area entries -> `functionalAreaScopes` as a JSON string array;
- optional domains -> `optionalDomains` as
  `{"domain": "...", "scenario": "..."}` objects;
- verified authorization -> `authorizationOutcome: verified`;
- remediated and retested authorization ->
  `authorizationOutcome: task-not-authorized-remediated`, plus
  `authorizationRemediationDomain`, `authorizationRemediationScenario`, and
  `authorizationRetestOutcome: verified-after-remediation`.

Any unsupported provider, mismatch, missing certificate, date mismatch, or
**I'm not sure** answer is a remediation outcome, not successful evidence. An
unresolved `Task not authorized` result reopens only the affected domain and
employee-security evidence; it must not discard valid endpoints, certificate,
or federation evidence.
Show the affected remediation step and keep the phase waiting.

If the administrator omits a required value or replies only with wording such
as "done", "all good", "continue", or "proceed", do not move to another field,
search workspace files, inspect environment variables, or infer the missing
evidence. Reopen the same structured form with only the missing or invalid
fields; never replace it with a free-text request for several numbered answers.
Preserve progress and stop until the structured form is complete.

After each structured response, write only the safe valid fields and the field
names that must be reopened to
`.local/connect/workday-da/workday-admin-partial-evidence.json`:

```json
{
  "fields": {
    "oauthClientId": "{validated non-secret client ID}"
  },
  "invalidFields": [
    "oauthTokenUrl"
  ]
}
```

Then persist the resumable partial result:

```powershell
python scripts/workday_connect.py record-administrator-evidence --phase workday-admin --evidence-file ".local\connect\workday-da\workday-admin-partial-evidence.json"
```

On resume, read the Workday administrator entry returned by `status`. Do not
redisplay a completed handoff. Reopen only `invalidFields` and
`outstandingFields`. If the packet output was lost, rerun
`workday-admin-packet`; it safely rebuilds and returns the same current
non-secret packet.

Never collect a secret, password, token, cookie, certificate body, or private
key. Write the response directly to
`.local/connect/workday-da/workday-admin-response.json` using a structured
file-write tool; never interpolate administrator-entered values into a
generated shell command. Pass the response once:

```powershell
python scripts/workday_connect.py record-workday-admin --response-file ".local\connect\workday-da\workday-admin-response.json"
```

If an exact replay matches persisted evidence, the controller returns
`replayed: true`. If it returns `driftDetected: true`, the Workday
administrator phase and downstream deployment state have been reopened.
Rebuild the packet and reconcile the changed API client, endpoint, or
administrator evidence before continuing.

Use these exact outcome values:

- `authenticationPolicyOutcome`: `existing-active-policy` or
  `reviewed-policy-activated`;
- `networkReadinessOutcome`: `confirmed-hosts-allowed` or
  `no-customer-firewall-change-required`.
- `apiClientOutcome`: `existing-client-verified` or
  `new-client-registered`;
- `clientGrantType`: `saml-bearer`;
- `includeWorkdayOwnedScope`: `yes`;
- `rolloutType`: `entire-workforce` or `limited-or-test`;
- `publicWorkerReportsOutcome` and `integrationPermissionsGetOutcome`:
  `get-permission-verified`;
- `authorizationOutcome`: `verified` or
  `task-not-authorized-remediated`.

For example:

```json
{
  "identityProviderOutcome": "verified-entra-issuer",
  "enabledServiceProviderId": "http://www.workday.com/{workdayTenant}",
  "certificateSelectionOutcome": "entra-signing-certificate-selected",
  "certificateValidityOutcome": "matches-verified-entra-certificate",
  "oauthClientId": "{non-secret Workday OAuth client ID}",
  "apiClientOutcome": "existing-client-verified",
  "clientGrantType": "saml-bearer",
  "includeWorkdayOwnedScope": "yes",
  "identityProviderSsoServiceUrl": "{EXPECTED_ENTRA_LOGIN_URL}",
  "signOnRedirectUrl": "{EXPECTED_ENTRA_REPLY_URL}",
  "oauthTokenUrl": "https://{workday-host}/ccx/oauth2/{tenant}/token",
  "restBaseUrl": "https://{workday-host}/ccx/api",
  "soapBaseUrl": "https://{workday-host}/ccx/service",
  "authenticationPolicyOutcome": "existing-active-policy",
  "networkReadinessOutcome": "confirmed-hosts-allowed",
  "rolloutType": "limited-or-test",
  "employeeSecurityGroup": "ESS Workday Pilot Employees",
  "publicWorkerReportsOutcome": "get-permission-verified",
  "integrationPermissionsGetOutcome": "get-permission-verified",
  "functionalAreaScopes": [
    "Core Payroll",
    "Organizations and Roles",
    "Staffing",
    "Time Off and Leave"
  ],
  "optionalDomains": [],
  "authorizationOutcome": "verified"
}
```

The controller validates the verified Entra issuer, Service Provider ID, HTTPS
endpoints, exact REST base suffix, certificate selection, and certificate-date
match before recording the non-secret identifiers, endpoints, and evidence
atomically. It captures the completed Entra and Workday phases as a tenant
foundation that can be reused for another environment or ESS HR agent. If the
administrator is not available, stop here; rerun
`workday-admin-packet` later without losing deployment progress.
