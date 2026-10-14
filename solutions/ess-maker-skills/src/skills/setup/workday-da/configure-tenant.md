<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phase 3 - Workday administrator

This phase never modifies Workday. The skill generates one handoff, validates
the administrator's non-secret response, derives deterministic endpoints, and
records evidence. All Workday tenant changes are performed by the Workday
administrator.

This phase starts only after Microsoft Entra sign-off is complete. Treat the
recorded Entra identifiers, certificate metadata, and already transferred
Base64 certificate as fixed inputs. Do not direct the maker back to the Entra
administrator, ask that administrator to repeat a task, or require access to
the Entra portal from this phase. A Workday-side mismatch remains a Workday
phase blocker unless the controller independently reports Entra target drift.

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
- For **Okta**, **Ping Identity**, or **Another sign-in provider**, render
  **Workday Administrator Steps - Existing non-Entra federation** and the
  coexistence or controlled-transition handoff below. Preserve the existing
  provider and guide the Workday administrator to either add a separate
  Microsoft Entra row for the approved target environment or perform a
  customer-approved transition of only that target environment. Do not return
  to Entra or re-engage the Entra app administrator. If the routing decision still
  needs customer governance approval, show the exact approval and inventory
  steps, preserve this phase, and resume the same handoff after approval
  instead of terminating the workflow.
- For **I'm not sure**, explain that Microsoft Entra issuers commonly contain
  `login.microsoftonline.com` or `sts.windows.net`, Okta issuers commonly
  contain `okta.com`, and Ping issuers commonly contain `pingone.com`,
  `pingidentity.com`, or an organization-specific Ping host. Stop and ask the
  Workday administrator to identify the enabled row in Workday; do not render
  either mutation handoff, the completion question, or the evidence form.

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
2. **Install the transferred signing certificate.** Use the Base64 certificate
   file already delivered through the approved customer channel during the
   completed Entra handoff. In Workday, run **Create x509 Public Key**, paste
   that public certificate, give it a customer-chosen recognizable name, and
   save it. Return to the enabled Microsoft Entra row and select that key in
   its **X509 Certificate** field. Do not open Entra or request another
   certificate transfer.

   Use `certificateSelectionQuestion` and `certificateValidityQuestion` from
   the packet to populate the corresponding fields in the consolidated form.
   Do not present them separately. Never suggest, prefill, or ask the administrator to confirm
   a guessed certificate name such as “Microsoft Azure Federated SSO
   Certificate.”

   Handle the answer as follows:
   - **The certificate transferred from the completed Entra handoff** - record
     `certificateSelectionOutcome` as
     `entra-signing-certificate-selected`. If the displayed expiration date
     exactly matches the verified Entra expiration date shown in the form,
     record
     `certificateValidityOutcome` as
     `matches-verified-entra-certificate`.
   - **A different existing Workday certificate** - stop. Do not reuse it.
     Select the Workday public key created from the transferred certificate,
     or keep the Workday phase blocked while the Workday administrator resolves
     the mismatch.
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
   firewall change is required. Do not wait until final Maker validation to
   discover a known allowlist requirement.

### Existing non-Entra federation coexistence or transition handoff

1. **Protect and inventory the existing federation.** In Workday, run **Edit
   Tenant Setup - Security**, open **SAML Setup**, and record the existing
   provider type, Issuer, **Used for Environments** assignment, selected X.509
   public key name, and applicable employee authentication-policy routing. Do
   not collect certificate contents, disable the row, overwrite its Issuer, or
   replace its certificate.
2. **Choose the customer-approved routing path.** The Workday administrator
   must select one of these safe paths:
   - where the tenant's supported Workday routing design permits it, add a
     separate Microsoft Entra SAML row for the approved target employee
     environment and scope its authentication-policy routing to the intended
     population; or
   - perform a controlled transition of only the target employee environment
     from the existing provider to Microsoft Entra during the customer's
     reviewed change window.

   Preserve every environment and population that is not in scope on the
   existing provider. Record the existing assignment needed for rollback. If
   the Workday administrator cannot approve either path yet, provide this
   inventory and routing decision as the next action, preserve the Workday
   phase, and resume here after approval. Do not restart the Entra handoff.
3. **Install the transferred signing certificate.** Use the Base64 certificate
   file already delivered during the completed Entra handoff. Run **Create x509
   Public Key**, paste that public certificate, give it a customer-chosen
   recognizable name, and save it. Do not modify the key selected by the
   existing non-Entra row.
4. **Create the separate Microsoft Entra row.** Add a SAML identity-provider
   row with the packet's exact expected Microsoft Entra Issuer, select the new
   Entra-derived public key, set the exact Workday Service Provider ID, set the
   identity-provider SSO service URL to the packet's **Login URL**, and set the
   sign-on redirect URL to the packet's **Reply URL**. Do not copy the existing
   provider's Issuer, endpoints, or certificate.
5. **Apply only the approved routing change.** For coexistence, assign the new
   Microsoft Entra row only to the approved target employee environment and
   apply the approved authentication-policy routing for the intended
   population. For a controlled transition, move only that approved target
   environment from the existing row to the new Entra row during the reviewed
   change window. Verify all out-of-scope assignments remain unchanged and
   keep the recorded rollback assignment until validation completes.
6. **Configure tenant security without weakening existing safeguards.** Enable
   **OAuth 2.0 Clients Enabled** and **SAML** when required. Preserve unrelated
   authentication policies, administrator safeguards, network restrictions,
   and non-Entra federation settings.
7. **Reuse or register the employee API client.** Reuse an approved client only
   when its **Client Grant Type** is **SAML Bearer**, its functional areas are
   exactly **Core Payroll**, **Organizations and Roles**, **Staffing**, and
   **Time Off and Leave**, and **Include Workday Owned Scope** is **Yes**.
   Otherwise register a new client with those exact settings.
8. **Configure employee domain security.** Grant the intended employee
   population **Get** on **Worker Data: Public Worker Reports** and
   **Integration Permissions**. Add another domain only for a named supported
   scenario. Preserve unrelated groups and permissions.
9. **Verify the connection endpoints.** Confirm the OAuth client ID and token
   endpoint, the REST base ending at `/ccx/api`, and the SOAP base ending at
   `/ccx/service` without the tenant name. Never return secrets or tokens.
10. **Review and activate the target authentication policy.** Confirm an active
    rule allows **SAML** for the intended target employees. Review and activate
    pending authentication-policy changes through the customer's approved
    process without changing routing for out-of-scope users.
11. **Confirm network readiness and final Entra-row values.** Confirm the REST
    and SOAP hosts are allowed, then verify the new Microsoft Entra row's
    Issuer, Service Provider ID, identity-provider SSO URL, redirect URL,
    selected certificate, and certificate expiration exactly match the packet.

### New Microsoft Entra federation handoff

1. **Confirm the greenfield path.** In Workday, run **Edit Tenant Setup -
   Security**, open **SAML Setup**, and
   confirm there is no enabled SAML identity-provider row for the employee
   environment being connected. Do not modify a row owned by another
   federation.
2. **Install the transferred signing certificate.** Use the Base64 certificate
   file already delivered during the completed Entra handoff. In Workday, run
   **Create x509 Public Key**, paste that public certificate, give it a
   customer-chosen recognizable name, and save it. Do not open Entra, request
   another certificate transfer, or collect the certificate body in chat.
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
selected above, repeat provider discovery within this Workday phase using the
same recorded Entra reference values. Do not return to the Entra phase or ask
the Entra app administrator to participate again.

Collect the Workday administrator's details in one response. Do not ask for
these values as a sequence of separate chat or form questions. The response
must contain all required evidence:

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
- API-client access: SAML Bearer, Include Workday Owned Scope, and all four
  required functional-area scopes;
- required employee access: Get permission for both `Worker Data: Public
  Worker Reports` and `Integration Permissions`;
- any additional domain paired with its named supported scenario, only when
  custom ESS scenarios require one.

Do not ask the Workday administrator to run an agent scenario or report an
authorization result in this phase. Connections and runtime configuration do
not exist yet. A maker-observed `Task not authorized` result is handled only
during Phase 6 after the same named scenario can be retested.

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
      { "label": "The certificate transferred from the completed Entra handoff" },
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
    "header": "API client access",
    "question": "Did the administrator verify SAML Bearer, Include Workday Owned Scope, and all four required functional areas: Core Payroll, Organizations and Roles, Staffing, and Time Off and Leave?",
    "options": [
      { "label": "Yes, SAML Bearer, Workday Owned Scope, and all four required functional areas are configured" },
      { "label": "No, one or more API client access settings are missing" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Required employee access",
    "question": "Did the administrator verify Get permission for both Worker Data: Public Worker Reports and Integration Permissions?",
    "options": [
      { "label": "Yes, Get permission is verified for Public Worker Reports and Integration Permissions" },
      { "label": "No, one or both required permissions are missing" },
      { "label": "I'm not sure" }
    ],
    "allowFreeformInput": false
  },
  {
    "header": "Additional scenario domains",
    "question": "Optional: only when custom ESS scenarios require extra Workday domains, enter one mapping per line as Domain | supported scenario. Otherwise omit this row or leave it blank."
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
    "header": "Workday administrator details",
    "question": "Paste the completed Workday administrator details in one response. Do not include passwords, client secrets, tokens, certificate contents, cookies, or private keys."
  }
]
```

Preserve the response unchanged. The controller recognizes the generated table
and common customer-facing labels and capitalization, rejects missing
mandatory labels, duplicate labels, or unknown labels, and maps only the
listed successful choices into the structured response object described
below. Omission of the optional **Additional scenario domains** row means
`optionalDomains: []`; do not ask for it again. Do not ask the customer to
reformat a recognizable response. Never infer a missing mandatory answer or
treat unlabeled prose as evidence:

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
- **The certificate transferred from the completed Entra handoff** ->
  `certificateSelectionOutcome: entra-signing-certificate-selected`;
- matching certificate expiration date ->
  `certificateValidityOutcome: matches-verified-entra-certificate`;
- approved existing client -> `apiClientOutcome:
existing-client-verified`;
- newly registered client -> `apiClientOutcome: new-client-registered`;
- successful **API client access** confirmation ->
  `clientGrantType: saml-bearer`, `includeWorkdayOwnedScope: yes`, and
  `functionalAreaScopes` populated with `Core Payroll`, `Organizations and
  Roles`, `Staffing`, and `Time Off and Leave`;
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
- successful **Required employee access** confirmation ->
  `publicWorkerReportsOutcome: get-permission-verified` and
  `integrationPermissionsGetOutcome: get-permission-verified`;
- omitted, blank, or **No additional scenario domains are required** ->
  `optionalDomains: []`;
- additional scenario-domain lines -> `optionalDomains` objects with one
  `domain` and one named supported `scenario` per line;
- a missing or uncertain required functional area, or an uncertain optional
  domain outcome -> stop for administrator remediation instead of submitting
  successful evidence.

Any unresolved provider identification or routing approval, mismatch, missing
certificate, date mismatch, or **I'm not sure** answer requires the applicable
guided step before successful evidence can be submitted. Preserve completed
evidence and resume the selected handoff rather than restarting the phase.

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
  `get-permission-verified`.

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
  "optionalDomains": []
}
```

The controller validates the verified Entra issuer, Service Provider ID, HTTPS
endpoints, exact REST base suffix, certificate selection, and certificate-date
match before recording the non-secret identifiers, endpoints, and evidence
atomically. It captures the completed Entra and Workday phases as a tenant
foundation that can be reused for another environment or ESS HR agent. If the
administrator is not available, stop here; rerun
`workday-admin-packet` later without losing deployment progress.
