<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phase 3 - Workday administrator

Before this phase's first question or handoff, apply the **Development progress
rule** in `SKILL.md`: show the current six-phase table for unfinished
Development, unless the orchestrator already showed it for this phase entry.
Do not repeat it for workbook corrections or insert a Development table into
a Test or Production plan.

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

After `record-entra` succeeds, always require fresh Workday administrator
confirmation and a completed Workday administrator workbook, even when the
Entra settings match a saved tenant foundation. An Entra workbook does not
verify Workday-side configuration. Do not mark this phase complete or continue
at Connections until the Workday response passes validation. Existing healthy
settings may be confirmed rather than changed.

Only a separately controller-verified Test or Production promotion may skip
these administrator handoffs using the recorded tenant foundation.

Identify the current federation before rendering a detailed handoff. The
phase boundary must already have asked
**Have you arranged for a Workday administrator to complete this step?**
and must not dispatch this
guide until the maker confirms engagement. Do not add a second
engagement question here. Use `identityProviderQuestion` from the packet in
one structured `vscode_askQuestions` call. Present its options unchanged and
leave the selection unset.

This question selects a safe handoff branch. It is not evidence that the
administrator finished configuration.

- For **Microsoft Entra ID**, label the workbook handoff **Existing
  Microsoft Entra federation** and note that the existing Entra row must match.
  Do not infer a match from the
  provider choice alone; the administrator must confirm the displayed
  Issuer exactly matches the verified Entra issuer.
- For **No enabled SAML row**, label the workbook handoff **New
  Microsoft Entra federation**; the worksheet explains how to add the Entra row.
- For **Okta**, **Ping Identity**, or **Another sign-in provider**, render
  the workbook handoff with the short safety note **Existing non-Entra
  federation: preserve the current provider. Use a separate Entra row for the
  approved target environment or a customer-approved transition of only that
  environment; preserve out-of-scope routing and the rollback assignment.**
  Keep this branch context because the workbook refers to the handoff for the
  coexistence or controlled-transition decision. Preserve the existing
  provider and guide the Workday administrator to either add a separate
  Microsoft Entra row for the approved target environment or perform a
  customer-approved transition of only that target environment. Do not return
  to Entra or re-engage the Entra app administrator. If the routing decision still
  needs customer governance approval, show only the relevant approval and inventory
  guidance, preserve this phase, and resume the same handoff after approval
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
administrator handoff**. It must contain
the administrator role, exact Workday tenant, known target environment, packet
reference values, workbook link, and the short selected-branch safety note.
The maker must be able to forward that section without copying values from
earlier chat messages.
The detailed workbook is the administrator's task guide. Do not render the
numbered administrator guides below, `packet.actions`, or an **Administrator
tasks** section in chat. Keep those guides as internal reference for a specific
question or failed workbook cell; show only the relevant help when needed.

Share `workbookFile` from the command result as the downloadable administrator
workbook. It must resolve to the checked-in
`[Workday administrator workbook](assets/workday-admin-workbook.xlsx)`.
Do not render `packet.captureInstructions` as a chat table;
the workbook is the single capture worksheet. Never render internal `fields`
names.

Render the following five bullets once in the concise handoff, without
restating them in surrounding prose:

> - **Share:** Send a copy to the Workday administrator; do not edit the original
>   template itself.
> - **Complete:** Use **Worksheet - Detailed**, follow each row's instructions,
>   and fill every cell in the **Your tenant values** column.
> - **Confirm:** Use the exact successful answer in **Example value** or the
>   listed choices in **What to record**, only after verifying the setting.
>   Leave incomplete confirmations blank.
> - **Return:** Send the completed, organization-approved readable `.xlsx` to
>   the maker. If encryption or sensitivity protection prevents validation,
>   ask your information protection administrator for an approved handoff.
> - **Protect:** Never include credentials, tokens, private keys, or certificate
>   contents in chat or the workbook, and do not bypass required protections.

When validation returns `details.fieldErrors`, show all returned labels and
corrections together, including the accepted answers for choice cells and the
required endpoint endings. Ask the administrator to correct those cells in
the same workbook, save it, and provide its full path again. Do not return to
Entra or repeat healthy handoff tasks. An encrypted or protected workbook requires an approved
readable copy or an information-protection handoff decision, not a password
in chat or an ad hoc decryption attempt. A chat reply such as **Yes** does not
correct the rejected workbook.

Network connectivity is a conditional infrastructure prerequisite, not a
required worksheet attestation. Do not add a **Network readiness** row or ask
for a generic readiness confirmation. Both Workday REST and SOAP endpoints
must be reachable from the Power Platform managed connector. If the customer
uses firewall or IP allowlists, or a connection test reports a network
failure, direct the maker to engage the customer's InfoSec or infrastructure
owner to allow the applicable Power Platform managed-connector outbound IP
ranges. If the endpoints are already reachable, do not require a firewall
change. Use the later connection and runtime tests as the reachability
evidence.

The guided external-prerequisites and final readiness profiles do not include
the standalone `WD-NET-001` firewall attestation. A completed Workday workbook
does not prove network reachability or satisfy that independent manual check.

Add one certificate bullet: use the certificate already transferred through
the approved channel during the Entra phase. Do not repeat that phase or
request another certificate transfer.

After sharing the concise handoff and workbook, record that it was presented
and is waiting for the administrator:

```powershell
python scripts/workday_connect.py administrator-stage --phase workday-admin --substage handoff-presented
python scripts/workday_connect.py administrator-stage --phase workday-admin --substage awaiting-completion
```

### Existing Microsoft Entra federation handoff

Internal reference only: do not render these task lists with the detailed
workbook. Use only the affected step for an explicit help request or correction.
This applies to all three federation guides below.

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
   Do not return employee membership lists.
6. **Verify the connection endpoints.** Open **View API Client** and confirm
   the OAuth client ID and token endpoint are available. Confirm the REST base
   ends at `/ccx/api` and the SOAP service base ends at `/ccx/service`; do not
   append the tenant name to the SOAP base. Never return a client secret,
   password, token, cookie, or certificate body.
7. **Verify employee authentication.** Open **Manage Authentication Policies**
   for the employee environment. Confirm an active rule is scoped to the ESS
   OAuth client identity and allows **SAML** for the intended employees. Do not
   replace administrator safeguards, existing network restrictions, or route
   this user-delegated setup through an Integration System User rule. If a
   policy change is required, review every pending authentication-policy
   change, then run **Activate All Pending Authentication Policy Changes**
   before reporting the policy as activated.
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
   **Integration Permissions**. Preserve unrelated groups and permissions.
9. **Verify the connection endpoints.** Confirm the OAuth client ID and token
   endpoint, the REST base ending at `/ccx/api`, and the SOAP base ending at
   `/ccx/service` without the tenant name. Never return secrets or tokens.
10. **Review and activate the target authentication policy.** Confirm an active
    rule is scoped to the ESS OAuth client identity and allows **SAML** for the
    intended target employees. Review and activate pending
    authentication-policy changes through the customer's approved process
    without changing routing for out-of-scope users.
11. **Confirm final Entra-row values.** Verify the new Microsoft Entra row's
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
   Employees.
7. **Verify the connection endpoints.** Open **View API Client** and confirm
   the OAuth client ID and token endpoint are available. Confirm the REST base
   ends at `/ccx/api` and the SOAP service base ends at `/ccx/service`; do not
   append the tenant name to the SOAP base. Never return a client secret,
   password, token, cookie, or certificate body.
8. **Verify employee authentication.** Open **Manage Authentication Policies**
   for the employee environment. Confirm an active rule is scoped to the ESS
   OAuth client identity and allows **SAML** for the intended employees. Do not
   replace administrator safeguards, existing network restrictions, or route
   this user-delegated setup through an Integration System User rule. If a
   change is required, review every pending authentication-policy change and
   run **Activate All Pending Authentication Policy Changes** before reporting
   the policy as activated.
9. Confirm whether the enabled row's Issuer, Service Provider ID,
    identity-provider SSO service URL, and sign-on redirect URL match the
    expected values.

Do not append these tasks to the shareable workbook handoff. The workbook
already tells the administrator what to return and where to find it, so do not
repeat an **Information to return to the maker** checklist or a separate return
worksheet.

After the concise handoff and workbook are shared, ask exactly:

**Has the Workday administrator completed their task?**

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

The completed workbook must contain all required evidence below. Do not ask
for these values as a sequence of separate chat or form questions:

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
- exact client grant type and Include Workday Owned Scope outcome;
- rollout type: entire workforce or limited/test;
- API-client access: SAML Bearer, Include Workday Owned Scope, and all four
  required functional-area scopes;
- required employee access: Get permission for both `Worker Data: Public
  Worker Reports` and `Integration Permissions`.

Do not ask the Workday administrator to run an agent scenario or report an
authorization result in this phase. Connections and runtime configuration do
not exist yet. A maker-observed `Task not authorized` result is handled only
during Phase 6 after the same named scenario can be retested.

The worksheet definition below is an internal mapping reference for the exact
successful values accepted by the controller. Do not render it as a chat table
or a sequence of forms. The concise handoff supplies the packet's expected
issuer, Service Provider ID, and verified certificate expiration date as
comparison references for the workbook:

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
    "question": "What did the administrator verify for the ESS OAuth client authentication policy and intended employee population?",
    "options": [
      { "label": "An existing active policy scopes the ESS OAuth client and allows SAML for the intended employees" },
      { "label": "A reviewed policy scoped to the ESS OAuth client was activated" },
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
  }
]
```

Leave every worksheet answer blank. Do not add `recommended`, `default`,
suggested-answer wording, or any equivalent preselection. The expected values
in the question text are comparison references, not answers.

After the administrator confirms completion, tell the maker:

> - Save the completed Workday administrator workbook on this computer.
> - In File Explorer, right-click the file and select **Copy as path**.
> - Paste the full path here, including the filename and `.xlsx` extension,
>   for example: `"C:\Users\YourName\Downloads\workday-admin-workbook.xlsx"`.

Do not require an upload or a file picker. Accept the surrounding quotes from
**Copy as path** and remove that outer pair before passing the path as a
single literal argument to the controller. Use the supplied local `.xlsx`
file directly. If it cannot be read, show the actual controller error and ask
for an accessible local path; do not guess another file or bypass permissions.
Do not ask the maker to paste the worksheet, retype the values, or hand-author
JSON. The controller rejects
missing mandatory labels, duplicate labels, unknown labels, formulas, and
unsafe workbook content, then maps only the listed successful choices into the
structured response object described below. Never infer a missing mandatory
answer or treat unlabeled prose as evidence:

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
- successful **API client access** confirmation ->
  `clientGrantType: saml-bearer`, `includeWorkdayOwnedScope: yes`, and
  `functionalAreaScopes` populated with `Core Payroll`, `Organizations and
  Roles`, `Staffing`, and `Time Off and Leave`;
- the entered connection/policy fields -> their corresponding controller
  keys;
- existing active policy -> `existing-active-policy`;
- reviewed and activated policy -> `reviewed-policy-activated`;
- configured entire workforce -> `rolloutType: entire-workforce`;
- configured limited/test population -> `rolloutType: limited-or-test`;
- an unconfigured or uncertain employee population -> stop for administrator
  remediation instead of submitting successful evidence;
- successful **Required employee access** confirmation ->
  `publicWorkerReportsOutcome: get-permission-verified` and
  `integrationPermissionsGetOutcome: get-permission-verified`;
- a missing or uncertain required functional area -> stop for administrator
  remediation instead of submitting successful evidence.

Any unresolved provider identification or routing approval, mismatch, missing
certificate, date mismatch, or **I'm not sure** answer requires the applicable
guided step before successful evidence can be submitted. Preserve completed
evidence and resume the selected handoff rather than restarting the phase.

If the administrator omits a required value or the maker replies only with
wording such as "done", "all good", "continue", or "proceed", do not move to
another field, search workspace files, inspect environment variables, or infer
the missing evidence. Name the missing or invalid customer-facing labels,
repeat the applicable handoff location or instruction, and ask the
administrator to correct those cells in the same workbook. Ask the maker to
save the corrected `.xlsx` file and provide its full path again. Do not reopen
a sequence of individual questions. Preserve progress and stop until the
workbook is complete.

After each workbook validation, write only the safe valid fields and the field
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
key. Pass the supplied workbook path as a single literal argument; never
execute path text as shell code or interpolate administrator-entered values
into a generated shell command:

```powershell
python scripts/workday_connect.py record-workday-admin --response-worksheet-file "<completed-workday-admin-workbook-full-path>"
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
  "clientGrantType": "saml-bearer",
  "includeWorkdayOwnedScope": "yes",
  "identityProviderSsoServiceUrl": "{EXPECTED_ENTRA_LOGIN_URL}",
  "signOnRedirectUrl": "{EXPECTED_ENTRA_REPLY_URL}",
  "oauthTokenUrl": "https://{workday-host}/ccx/oauth2/{tenant}/token",
  "restBaseUrl": "https://{workday-host}/ccx/api",
  "soapBaseUrl": "https://{workday-host}/ccx/service",
  "authenticationPolicyOutcome": "existing-active-policy",
  "rolloutType": "limited-or-test",
  "publicWorkerReportsOutcome": "get-permission-verified",
  "integrationPermissionsGetOutcome": "get-permission-verified",
  "functionalAreaScopes": [
    "Core Payroll",
    "Organizations and Roles",
    "Staffing",
    "Time Off and Leave"
  ]
}
```

The controller validates the verified Entra issuer, Service Provider ID, HTTPS
endpoints, exact REST base suffix, certificate selection, and certificate-date
match before recording the non-secret identifiers, endpoints, and evidence
atomically. It captures the completed Entra and Workday phases as a tenant
foundation that can be reused for another environment or ESS HR agent. If the
administrator is not available, stop here; rerun
`workday-admin-packet` later without losing deployment progress.
