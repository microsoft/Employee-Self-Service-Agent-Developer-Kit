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
before rendering a detailed handoff. The phase boundary must already have
asked **Have you looped in the Workday administrator?** and must not dispatch
this guide until the maker confirms engagement. Do not add a second
engagement question here. Use `identityProviderQuestion` from the packet in
one structured `vscode_askQuestions` call. Present its options unchanged and
leave the selection unset.

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

Render the selected branch as one standalone section titled **Workday
administrator handoff - share this whole section**. It must contain the
administrator role, exact Workday tenant and environment, packet reference
values, one capture table, and every applicable numbered task. The maker must
be able to forward that one section without copying values from earlier chat
messages.

Before the numbered tasks, render every entry from the packet's
`captureInstructions` as one table with these exact columns:

| Information to capture | Where to find it | What to record | Example value | Your tenant values |
| ---------------------- | ---------------- | -------------- | ------------- | ------------------ |

Use each entry's `information`, `portalLocation`, `instruction`, and
`exampleValue` values for the first four columns. Leave every cell in **Your
tenant values** blank. Escape literal table pipes as `\|` and use `<br>` for a
line break inside a cell. Tell the administrator to complete that final column
and return the whole table to the maker, who will paste it into the agent chat.
Never render internal `fields` names. This table is both the capture guide and
the return worksheet. Do not render the packet's `informationToReturn` list or
a second worksheet. Keep the numbered tasks focused on actions; do not repeat
table locations, capture instructions, or return-value lists unless necessary
to perform the change. Do not ask for a field after completion unless it
appeared as a row in the shareable table.

After rendering the complete handoff, record that it was presented and is
waiting for the administrator:

```powershell
python scripts/workday_connect.py administrator-stage --phase workday-admin --substage handoff-presented
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
     `entra-signing-certificate-selected`. If the displayed expiration date
     exactly matches the verified Entra expiration date shown in the form,
     record
     `certificateValidityOutcome` as
     `matches-verified-entra-certificate`.
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
   population. For a limited/test rollout, configure the intended Workday
   security group and include the test employee; never default to All
   Employees. Grant **Get** on
   **Worker Data: Public Worker Reports** and **Integration Permissions**.
   Do not treat the functional-area scopes from step 4 as domain permissions.
   Add another domain only when it is tied to a named supported scenario.
   Do not return employee membership lists.
6. **Verify the connection endpoints.** Open **View API Client** and confirm
   the OAuth client ID and token endpoint are available. Confirm the REST base
   ends at `/ccx/api` and the SOAP service base ends at `/ccx/service`; do not
   append the tenant name to the SOAP base. Never return a client secret,
   password, token, cookie, or certificate body.
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
7. **Verify the connection endpoints.** Open **View API Client** and confirm
   the OAuth client ID and token endpoint are available. Confirm the REST base
   ends at `/ccx/api` and the SOAP service base ends at `/ccx/service`; do not
   append the tenant name to the SOAP base. Never return a client secret,
   password, token, cookie, or certificate body.
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
10. Confirm whether the enabled row's Issuer, Service Provider ID,
    identity-provider SSO service URL, and sign-on redirect URL match the
    expected values.

End the shareable handoff after the applicable numbered tasks. The capture
table already tells the administrator what to return and where to find it, so
do not repeat an **Information to return to the maker** checklist or a separate
return worksheet.

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

Collect the completed five-column table in one response. Do not ask for these
values as a sequence of separate chat or form questions. The table retains all
required evidence:

- confirmation that the enabled Microsoft Entra SAML row's Issuer, Service
  Provider ID, identity-provider SSO service URL, and sign-on redirect URL
  exactly match the expected values;
- confirmation that the Entra-derived certificate is selected;
- confirmation that its displayed expiration date exactly matches the
  verified Entra expiration date;
- Workday OAuth client ID;
- OAuth token URL;
- REST base URL ending at `/ccx/api`;
- SOAP base URL;
- authentication-policy outcome;
- network-readiness outcome.
- whether an approved existing API client was verified or a new one was
  registered;
- exact client grant type and Include Workday Owned Scope outcome;
- rollout type: entire workforce or limited/test;
- `Worker Data: Public Worker Reports` Get-permission outcome;
- `Integration Permissions > Get` outcome;
- confirmation that all four required API functional-area scopes are present;
- any additional domain paired with its named supported scenario, only when
  custom ESS scenarios require one;
- authorization outcome, including whether a bounded `Task not authorized`
  remediation was required; when it was, the affected domain, named scenario,
  and successful retest outcome.

The worksheet definition below is an internal mapping reference for the exact
successful values accepted by the controller. Do not render it after the
handoff table. Substitute the packet's expected issuer, Service Provider ID,
and verified certificate expiration date when building the table:

```json
[
  {
    "header": "SAML row settings",
    "question": "In Workday, open Edit Tenant Setup - Security -> SAML Setup. On the enabled Microsoft Entra identity-provider row, do Issuer, Service Provider ID, identity-provider SSO service URL, and sign-on redirect URL exactly match {EXPECTED_ENTRA_ISSUER}, {EXPECTED_SERVICE_PROVIDER_ID}, {EXPECTED_ENTRA_LOGIN_URL}, and {EXPECTED_ENTRA_REPLY_URL}?",
    "options": [
      { "label": "Yes, all four values match exactly" },
      { "label": "No, one or more values are different" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
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
    "header": "Certificate expiration",
    "question": "Does the selected Workday certificate expiration date exactly match {CERTIFICATE_VALID_TO}?",
    "options": [
      { "label": "Yes, the expiration date matches exactly" },
      { "label": "No, the expiration date is different" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
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
    "options": [{ "label": "Yes" }, { "label": "No or not sure" }],
    "allowFreeformInput": false
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
    "question": "Which employee population did the Workday administrator configure and verify for this rollout?",
    "options": [
      { "label": "Entire workforce - All Employees access is configured" },
      {
        "label": "Limited or test population - the intended Workday security group and test employee access are configured"
      },
      { "label": "The employee population is not configured or I'm not sure" }
    ],
    "allowFreeformInput": false
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
    "question": "Did the administrator verify that the API client includes all four required functional areas: Core Payroll, Organizations and Roles, Staffing, and Time Off and Leave?",
    "options": [
      { "label": "Yes, all four required functional areas are present" },
      { "label": "No, one or more required functional areas are missing" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Optional domains",
    "question": "Are additional Workday domains required for named custom ESS scenarios beyond the standard setup?",
    "options": [
      { "label": "No additional domains are required" },
      { "label": "Yes, additional supported scenarios require domains" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Additional domain mappings",
    "question": "Only when additional domains are required: enter one per line as Domain | supported scenario. Otherwise leave this blank."
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

Leave every worksheet answer blank. Do not add `recommended`, `default`,
suggested-answer wording, or any equivalent preselection. The expected values
in the question text are comparison references, not answers.

After the administrator confirms completion, use one
`vscode_askQuestions` call containing exactly one free-form question:

```json
[
  {
    "header": "Workday administrator return table",
    "question": "Paste the completed Workday administrator table in one response, including the header and every row. Do not include passwords, client secrets, tokens, certificate contents, cookies, or private keys."
  }
]
```

The response is a strict five-column table, not free-form evidence. Preserve it
unchanged. The controller reads only the exact **Information to capture**
labels and **Your tenant values** cells, rejects missing, duplicate, or unknown
labels, and maps only the listed successful choices into the structured
response object described below. The legacy exact labeled worksheet remains
accepted for resume compatibility. Never parse, rename, infer, or normalize an
answer in the skill:

Certificate comparisons are date-only. Do not ask either administrator for a
timestamp, time, or timezone. Accept the portal's displayed certificate date
in a common numeric or month-name format; the controller ignores any supplied
time component.

- an applicable Microsoft Entra branch plus
  **Yes, all four values match exactly** ->
  `identityProviderOutcome: verified-entra-issuer`,
  `enabledServiceProviderId: {EXPECTED_SERVICE_PROVIDER_ID}`,
  `identityProviderSsoServiceUrl: {EXPECTED_ENTRA_LOGIN_URL}`, and
  `signOnRedirectUrl: {EXPECTED_ENTRA_REPLY_URL}`;
- a different or uncertain Issuer, Service Provider ID, SSO service URL, or
  sign-on redirect URL -> stop for administrator remediation instead of
  submitting successful evidence;
- **The new certificate created from the Entra Base64 file** ->
  `certificateSelectionOutcome: entra-signing-certificate-selected`;
- matching certificate expiration date ->
  `certificateValidityOutcome: matches-verified-entra-certificate`;
- approved existing client -> `apiClientOutcome:
existing-client-verified`;
- newly registered client -> `apiClientOutcome: new-client-registered`;
- **SAML Bearer** -> `clientGrantType: saml-bearer`;
- **Yes** for Workday owned scope -> `includeWorkdayOwnedScope: yes`;
- the entered connection/policy fields -> their corresponding controller
  keys;
- existing active policy -> `existing-active-policy`;
- reviewed and activated policy -> `reviewed-policy-activated`;
- both hosts allowed -> `confirmed-hosts-allowed`;
- no firewall change required ->
  `no-customer-firewall-change-required`.
- configured entire workforce -> `rolloutType: entire-workforce`;
- configured limited/test population -> `rolloutType: limited-or-test`;
- an unconfigured or uncertain employee population -> stop for administrator
  remediation instead of submitting successful evidence;
- each verified domain permission ->
  `get-permission-verified`;
- **Yes, all four required functional areas are present** ->
  `functionalAreaScopes` populated with `Core Payroll`,
  `Organizations and Roles`, `Staffing`, and `Time Off and Leave`;
- **No additional domains are required** -> `optionalDomains: []`;
- additional domain lines -> `optionalDomains` objects with one `domain` and
  one named supported `scenario` per line;
- a missing or uncertain required functional area, or an uncertain optional
  domain outcome -> stop for administrator remediation instead of submitting
  successful evidence;
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
evidence. Render one mini-worksheet containing only the missing or invalid
customer-facing labels and repeat the applicable handoff location or
instruction. Then use one free-form question to collect that completed
mini-worksheet. Do not reopen a sequence of individual questions. Preserve
progress and stop until the worksheet is complete.

After each worksheet response, write only the safe valid fields and the field
names that must be reopened to
`.local/connect/workday-da/workday-admin-partial-evidence.json`:

```json
{
  "fields": {
    "oauthClientId": "{validated non-secret client ID}"
  },
  "invalidFields": ["oauthTokenUrl"]
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
key. Write the exact table response directly to
`.local/connect/workday-da/workday-admin-return-worksheet.txt`; never
interpolate administrator-entered values into a generated shell command. Pass
the worksheet once:

```powershell
python scripts/workday_connect.py record-workday-admin --response-worksheet-file ".local\connect\workday-da\workday-admin-return-worksheet.txt"
```

The controller reconciles the administrator evidence with automatic readiness
checks before this phase completes. If a live check
or guided setting still needs attention, keep the owning phase open and show
the returned remediation. Do not direct the customer to run a separate
readiness profile or display internal validation identifiers.

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
