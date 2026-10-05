<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phase 2 - Microsoft Entra

This phase guides an administrator through the required Entra changes and
records the administrator's non-secret response.
It requires an Application Administrator or Cloud Application Administrator;
administrator consent may require a consent-capable role.

`workday_connect.py` does not create or modify the Entra application. It
validates the structured response and records evidence. The maker may not hold
an Entra administrator role, so this release does not authenticate the maker
to Microsoft Graph or make maker-owned Entra API calls. Role-aware execution
will trigger those live API checks later. For now, use the guided handoff to
the Entra administrator. Do not say that the skill will create, configure,
update, grant, enable, or independently verify an Entra setting.

## Prepare the guided handoff

1. Read the canonical Entra tenant ID and Workday tenant from controller state.
   If the Workday tenant is missing, ask for either the exact tenant name or a
   Workday OAuth token, SAML reply, or authentication-gateway URL that contains
   it. The controller safely extracts the tenant name from those recognized URL
   shapes. Use this exact `vscode_askQuestions` form:

   ```json
   [
     {
       "header": "Workday tenant",
       "question": "Enter the Workday tenant name, or paste a Workday signed-in, OAuth token, SAML reply, or authentication-gateway URL that contains it. For example, contoso_impl or https://wd5.myworkday.com/contoso_impl/d/home.htmld."
     }
   ]
   ```

   Leave the answer unset. Explain that this identifies the tenant's technical
   name, not its friendly company name or Workday environment label. Pass the
   answer directly to the controller, which validates a tenant name or safely
   extracts it from the recognized Workday URL shapes:

   ```powershell
   python scripts/workday_connect.py set-workday-tenant --tenant "{tenant}"
   ```

2. Do not align Azure CLI, query the maker's directory roles, discover
   applications, or reread configuration through Microsoft Graph. Those live
   checks require role-aware Entra administrator execution.
3. Give the administrator the canonical tenant ID, Workday tenant, expected
   Service Provider ID `http://www.workday.com/{workdayTenant}`, and the
   administrator guide below. The administrator must identify the selected
   directory and exact enterprise-application/app-registration pairing.

<!--
Role-aware execution will trigger these live Entra API checks later.
For now, Workday Connect uses a guided Entra administrator handoff.

The deferred automated path writes entra-discovery.json and runs:
python scripts/workday_connect.py entra-handoff --discovery-file ".local\connect\workday-da\entra-discovery.json"
-->

Use this current phase guide and the controller contract only. Do not inspect
or reuse the legacy `src/skills/setup/workday/` procedure to fill gaps.

Do not render the handoff until the maker confirms that the administrator is
engaged. Do not add a separate apply approval: the controller does not perform
these portal changes.

## Reuse an existing tenant foundation

Do not silently reuse Entra configuration from tenant-scoped evidence while
live role-aware verification is deferred. Show the exact required Entra role.
Add a consent-capable administrator only when administrator consent is
required. Then use this exact `vscode_askQuestions` form:

```json
[
  {
    "header": "Microsoft Entra administrator",
    "question": "Have you looped in the Microsoft Entra administrator to complete the remaining portal action?",
    "options": [
      { "label": "Yes, the Microsoft Entra administrator is engaged" },
      {
        "label": "No, I still need to engage the Microsoft Entra administrator"
      }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. If the administrator is not engaged, pause before
showing the portal instructions. Explain that no Entra portal change was made
and that the lifecycle will resume from the same phase. Do not request the
administrator's name, credentials, or other identifying information. This
engagement answer is not configuration evidence.

After **Yes**, record the engagement boundary:

```powershell
python scripts/workday_connect.py administrator-stage --phase entra --substage administrator-engaged
```

Then generate the guided handoff packet:

```powershell
python scripts/workday_connect.py entra-handoff
```

This command reads only the recorded lifecycle state. It does not authenticate
to Microsoft Graph, discover applications, or make an Entra change. Use the
returned `packet` for every packet-driven value below.

Render one standalone section titled **Microsoft Entra administrator handoff -
share this whole section**. It must contain the administrator role, canonical
tenant ID, expected Workday Service Provider ID, the numbered tasks below, and
the complete field-capture instructions and **Information to return to the
maker** checklist. The administrator identifies the selected directory and
exact enterprise application/app-registration identity. The maker must be
able to forward that one section without copying values from earlier chat
messages.

Before the numbered tasks, tell the administrator:

> Record the values in the following table while completing the tasks. The
> maker will be asked for these exact values after you finish, so do not close
> the portal until they have been captured. Return only non-secret values. Do
> not return credentials, tokens, certificate contents, or private keys.

Render every entry from the packet's `captureInstructions` as a table with
columns **Information to capture**, **Where to find it**, and **What to
record**. Use each entry's `information`, `portalLocation`, and `instruction`
values respectively. Never show the internal `fields` names or state keys such
as `microsoftEntraIdentifier` or `scopeGuid`. Keep the portal navigation and
capture instruction verbatim. This table must appear before the administrator
starts the numbered tasks, not only after the completion question.

After rendering the complete handoff, persist the presentation and waiting
boundaries:

```powershell
python scripts/workday_connect.py administrator-stage --phase entra --substage handoff-presented
python scripts/workday_connect.py administrator-stage --phase entra --substage awaiting-completion
```

## Administrator guide for missing or changed settings

The Entra administrator must identify the exact application by the expected
Service Provider ID and matching Application ID. Never select an application
by display name alone.

1. **Identify the existing Workday SSO application.** First confirm whether
   Microsoft Entra SSO for Workday is already established:
   - If it is already established, use the existing Workday enterprise
     application. Do not create another application.
   - If it is not established, follow the Microsoft Learn
     [Workday SSO tutorial](https://learn.microsoft.com/entra/identity/saas-apps/workday-tutorial).
     That tutorial directs the Entra administrator to select
     **Enterprise applications -> New application**, search for **Workday**,
     and add it from the Microsoft Entra application gallery.

   Confirm that the selected application's SAML **Identifier (Entity ID)** is
   `http://www.workday.com/{workdayTenant}`. If more than one application uses
   that same Identifier, the Entra administrator must identify the
   authoritative application and resolve the duplicate before continuing.

2. **Configure SAML.** Open **Enterprise applications -> the exact Workday
   application -> Single sign-on -> SAML**. Set **Identifier (Entity ID)** to
   `http://www.workday.com/{workdayTenant}`. Create or activate the signing
   certificate required by the tenant. On the **SAML Signing Certificate**
   card, select the **Edit** pencil. In the panel that opens, set the
   **Signing Option** field to **Sign SAML response and assertion**.
   Record the exact **Reply URL**. Confirm the displayed **Microsoft Entra
   Identifier** and **Login URL** match the expected values shown in this
   handoff; the maker does not need to transcribe those derived values.
3. **Keep the two identifiers distinct.** The Workday SAML Service Provider ID
   is `http://www.workday.com/{workdayTenant}`. The Entra application ID URI is
   `api://{entraAppId}`. Never copy one into the other field.
4. **Confirm the application pairing.** Match the enterprise application to
   its app registration by the same Application ID. Do not pair by display
   name. Stop on no match or more than one matching app registration.
5. **Expose the connector scope without replacing existing configuration.**
   Open **App registrations -> the exact Workday application -> Expose an API**.
   Preserve every unrelated existing scope and authorized client. Set
   the Application ID URI to `api://{entraAppId}`, add or repair only the
   `user_impersonation` scope, then add authorized client application
   `4e4707ca-5f53-46a6-a819-f7765446e6ff` for that scope.
6. **Add delegated permissions.** Open **App registrations -> the exact
   Workday application -> API permissions -> Add a permission -> Microsoft
   Graph -> Delegated permissions**. Add `openid`, `profile`, and `User.Read`,
   preserving unrelated existing permissions. Then select **Grant admin
   consent** using a consent-capable administrator.
7. **Configure assignment.** Open **Enterprise applications -> the exact
   Workday application -> Users and groups**. If assignment is required,
   assign the intended ESS employee security group; prefer a maintained group
   over individual users.
8. **Configure NameID.** Open **Enterprise applications -> the exact Workday
   application -> Single sign-on -> Attributes & Claims**. Edit **Unique User
   Identifier (Name ID)** so the source attribute equals the Workday User Name
   used by the tenant, commonly `user.mail` or `user.userPrincipalName`.

End the shareable handoff with **Information to return to the maker** and show
every item from the packet's `informationToReturn` list. State that each later
follow-up question corresponds to a value or outcome already identified in the
capture table. Do not ask for a field after completion unless the shareable
handoff told the administrator where to capture it.

Then render a section titled **Microsoft Entra administrator return
worksheet** using the template below. The administrator can complete this
worksheet and return it to the maker through the customer's approved
collaboration channel. Do not include internal field names or ask the
administrator to enter answers directly into the maker's Copilot session.
State that every line is required and must have an answer before the worksheet
is returned. The certificate thumbprint and expiration date are shown on the
active certificate row under **Enterprise applications -> the exact Workday
application -> Single sign-on -> SAML -> SAML Signing Certificate**.

```text
Directory name:
Enterprise application:
Application ID:
Selected Reply URL:
NameID source:
SAML signing: [Sign SAML response and assertion | Sign SAML assertion | Sign SAML response]
Certificate thumbprint (active certificate row):
Certificate expiration date (active certificate row):
SAML configuration: [Yes, confirmed | No, configuration is incomplete or different | I'm not sure]
Signing certificate: [Yes, confirmed | No, certificate setup or transfer is incomplete | I'm not sure]
Authorized connector: [Yes, confirmed | No, it is not authorized | I'm not sure]
Permissions and consent: [Yes, permissions and consent are confirmed | No, permissions or consent are incomplete | I'm not sure]
Employee assignment: [Yes, access is confirmed or assignment is not required | No, required assignment is incomplete | I'm not sure]
Existing configuration: [Preserved without changes | Remediated without replacing unrelated configuration | Not preserved or I'm not sure]
```

After the worksheet, ask exactly:

**Has the Microsoft Entra administrator completed the tasks in this handoff?**

Do not treat the answer as a broad "everything is done" confirmation or as
configuration evidence. It is only the coordination boundary before answer
collection and verification.

Present **Yes, the tasks are complete** and **Not yet** as the standard
choices, initially unset and with custom entry disabled. **Not yet** keeps the
phase waiting and does not show the response form. Only after **Yes** may the
skill record the completion boundary and collect evidence.

After **Yes**, run:

```powershell
python scripts/workday_connect.py administrator-stage --phase entra --substage completion-confirmed
```

Then collect the complete **Information to return to the maker** response from
the Entra administrator. It must include the selected directory, exact
enterprise-application/app-registration pairing, identifiers, Reply URL,
safe certificate metadata, configured outcomes, and preservation outcomes.
Store exact non-secret values as `observedValue` where required. Object IDs,
the scope GUID, derived tenant URLs, and complete URI lists are not required
from the maker. A reply such as "done", "all good", "continue", or "proceed"
is not evidence and must not be converted into administrator attestation.

The VS Code question UI renders an array of questions as a sequential wizard.
Do not submit one question per worksheet field. Use one
`vscode_askQuestions` call containing exactly one free-form question:

```json
[
  {
    "header": "Entra return worksheet",
    "question": "Paste the completed Microsoft Entra administrator return worksheet in one response. Keep every field label with its answer. Do not include credentials, tokens, certificate contents, or private keys."
  }
]
```

The response is a strict labeled worksheet, not free-form evidence. Preserve
the exact labels and answers unchanged. The controller rejects missing,
duplicate, or unknown labels, maps only the listed successful choices, and
then validates the resulting structured verification payload. Never parse,
rename, infer, or normalize an answer in the skill.

After submission, validate the complete worksheet once. If fields are missing,
invalid, or internally inconsistent, retain every safe valid answer and ask
for one revised worksheet containing only the returned `invalidFields` and
`outstandingFields`. Do not replay the full worksheet or revert to one-by-one
chat questions. Before the retry question, repeat the applicable
`captureInstructions` portal location and render a fill-in template containing
only the missing or invalid customer-facing labels. For example:

```text
Find both values at:
Enterprise applications -> the exact Workday application -> Single sign-on
-> SAML -> SAML Signing Certificate -> active certificate row

Certificate thumbprint:
Certificate expiration date:
```

Then ask for that completed mini-template in one free-form response. Do not
say only "paste a revised worksheet" without the location and template.

Do not perform a maker-authenticated Graph reread after the administrator
submits the response. Role-aware execution will perform those real API checks
later.

Persist the selected directory display name, application display name and
Application ID, derived `entraAppIdUri`, derived
`workdaySamlEntityId`, derived `microsoftEntraIdentifier`, derived
`entraLoginUrl`, the selected `replyUrl`, and safe certificate metadata. Object
IDs and the scope GUID are optional future role-aware verification evidence;
do not ask the maker to transcribe them. Never persist certificate contents.

For a portal-only setting that Graph cannot prove, include its non-secret
administrator confirmation in the `checks` object rather than claiming the
skill changed it.

When a structured response contains both valid and invalid fields, write the
safe validated values and the names to reopen to
`.local/connect/workday-da/entra-partial-evidence.json`, then run:

```powershell
python scripts/workday_connect.py record-administrator-evidence --phase entra --evidence-file ".local\connect\workday-da\entra-partial-evidence.json"
```

On resume, use the Entra administrator entry returned by `status`. Do not
redisplay a completed handoff; collect only its `invalidFields` and
`outstandingFields`.

Write the administrator's exact labeled response directly to
`.local/connect/workday-da/entra-return-worksheet.txt`, then run:

```powershell
python scripts/workday_connect.py record-entra --verification-worksheet-file ".local\connect\workday-da\entra-return-worksheet.txt"
```

If an exact replay matches the persisted evidence, the controller returns
`replayed: true`. If a completed phase now returns `driftDetected: true`, the
controller has reopened Entra and invalidated downstream deployment state.
Repeat the guided administrator handoff for the changed target; do not
continue from the stale tenant foundation.

The JSON must contain the administrator-confirmed directory display name,
Workday application display name and Application ID, selected Reply URL, safe
certificate metadata, and one evidence object for each check. The controller
adds the already verified tenant ID and derives the Entity ID, Application ID
URI, Microsoft Entra Identifier, and Login URL. Object IDs and the scope GUID
are optional and must not be invented when they were not collected:

```json
{
  "selectedDirectory": {
    "displayName": "Contoso"
  },
  "application": {
    "displayName": "Workday",
    "appId": "11111111-1111-1111-1111-111111111111"
  },
  "replyUrl": "https://{approved-workday-reply-url}",
  "certificate": {
    "thumbprint": "{thumbprint}",
    "validFrom": "2026-01-01T00:00:00Z",
    "validTo": "2027-01-01T00:00:00Z"
  },
  "checks": {
    "samlMode": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation"
    },
    "signingCertificate": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation"
    },
    "connectorPreauthorized": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation"
    },
    "graphDelegatedPermissions": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation"
    },
    "adminConsent": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation"
    },
    "userAssignment": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation"
    },
    "nameId": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation",
      "observedValue": "user.userPrincipalName"
    },
    "samlSigningOption": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation",
      "observedValue": "Sign SAML response and assertion"
    },
    "existingScopesPreserved": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation",
      "observedValue": "preserved"
    },
    "authorizedClientsPreserved": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation",
      "observedValue": "preserved"
    },
    "permissionsPreserved": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation",
      "observedValue": "preserved"
    }
  }
}
```

For this guided release, use `administrator-attestation` with outcome
`confirmed`. Role-aware execution may later supply `microsoft-graph` with
outcome `verified`. For the three preservation checks, use `preserved` when
the required setting already coexists with unrelated configuration and
`remediated` when a targeted repair was required without replacing unrelated
values. The command rejects a different tenant and incomplete,
provenance-free, or internally inconsistent evidence. Resume by showing only
failed remediation, not by repeating the full guide.
