<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phase 2 - Microsoft Entra

This phase discovers one exact Workday SAML application, then guides an
administrator through the required Entra changes and verifies the result.
It requires an Application Administrator or Cloud Application Administrator;
administrator consent may require a consent-capable role.

`workday_connect.py` does not create or modify the Entra application. It
validates exact discovery, generates one administrator handoff, validates the
Graph reread, and records evidence. Do not say that the skill will create,
configure, update, grant, or enable an Entra setting.

## Discover before handoff

1. Read the canonical Entra tenant ID and Workday tenant from controller state.
   If the Workday tenant is missing, ask for the signed-in Workday URL and
   validate its first path segment against
   `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`, then run:

   ```powershell
   python scripts/workday_connect.py set-workday-tenant --tenant "{tenant}"
   ```
2. Align Azure CLI to the canonical Entra tenant. Explain that this is the
   Microsoft Graph/Azure CLI credential store before any sign-in.
3. Query the signed-in user's directory roles by stable role-template ID.
   Never authorize from a localized display name and never downgrade a failed
   privileged-role query to self-attestation.
4. List application and service-principal identity together. Match only exact,
   normalized equality with:

   ```text
   http://www.workday.com/{workdayTenant}
   ```

   Never select by display name alone and never use substring matching.

Build discovery JSON with `displayName`, application `appId`, application
`objectId`, service-principal `servicePrincipalId`, and `identifierUris`.
Write it directly to `.local/connect/workday-da/entra-discovery.json` using a
structured file-write tool; never interpolate Graph values into a generated
shell command. Then run:

```powershell
python scripts/workday_connect.py administrator-stage --phase entra --substage administrator-engaged
python scripts/workday_connect.py entra-handoff --discovery-file ".local\connect\workday-da\entra-discovery.json"
```

If no exact app exists, include `"allowCreate": true` only after the user
chooses to create the Workday gallery app. If multiple apps have the exact
Service Provider ID, stop for administrator remediation.

Use this current phase guide and the controller contract only. Do not inspect
or reuse the legacy `src/skills/setup/workday/` procedure to fill gaps.

Show the returned target, Service Provider ID, Entra Application ID URI,
permissions, and administrator actions once as one handoff. Do not add a
separate apply approval: the controller does not perform these portal changes.

## Reuse an existing tenant foundation

If `foundationReuse.eligible` is `true`, do not ask an administrator to repeat
the setup. Reread the exact application and service principal through Microsoft
Graph and verify the settings listed below. If every check passes, call
`record-entra`; it restores the matching Workday administrator phase from
tenant-scoped evidence and the lifecycle continues at Connections.

If a check fails, show only the affected remediation step from the
administrator guide. Do not present the entire guide as mandatory merely
because the user selected another environment, agent, or maker account.

Before showing any administrator portal action that remains after discovery
and tenant-foundation reconciliation, show the exact required Entra role. Add
a consent-capable administrator only when the handoff says administrator
consent is still required. Then use this exact `vscode_askQuestions` form:

```json
[
  {
    "header": "Microsoft Entra administrator",
    "question": "Is the required Microsoft Entra administrator available to complete the remaining portal action?",
    "options": [
      { "label": "Yes, the administrator is available" },
      { "label": "No, the administrator is unavailable" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. If the administrator is unavailable, pause before
showing the portal instructions. Explain that no Entra portal change was made
and that the lifecycle will resume from the same phase. Do not request the
administrator's name, credentials, or other identifying information. This
availability answer is not authorization evidence; the stable role-template
check and verified Graph reread remain authoritative.

After the handoff is presented and the administrator is working, persist the
waiting boundary:

```powershell
python scripts/workday_connect.py administrator-stage --phase entra --substage awaiting-completion
```

If `requiresRediscovery` is `true`, ask an Entra administrator to open
**Microsoft Entra admin center -> Enterprise applications -> New application**,
find the official **Workday** gallery application, and create it in the selected
tenant. Stop after creation and repeat exact application discovery. Entra must
assign the application and service-principal IDs before later settings can be
planned safely.

## Administrator guide for missing or changed settings

Use the exact application returned by discovery. Never select another
application by display name alone.

1. **Configure SAML.** Open **Enterprise applications -> the exact Workday
   application -> Single sign-on -> SAML**. Set **Identifier (Entity ID)** to
   `http://www.workday.com/{workdayTenant}`. Create or activate the signing
   certificate required by the tenant. Under **SAML Signing Certificate ->
   Edit**, set **Signing Option** to **Sign SAML response and assertion**.
   Record the exact **Reply URL**, **Microsoft Entra Identifier**, and
   **Login URL** shown for this selected directory. Do not reconstruct them
   from another tenant or application.
2. **Keep the two identifiers distinct.** The Workday SAML Service Provider ID
   is `http://www.workday.com/{workdayTenant}`. The Entra application ID URI is
   `api://{entraAppId}`. Never copy one into the other field.
3. **Confirm the application pairing.** Match the enterprise application to
   its app registration by the same Application ID. Do not pair by display
   name. Stop on no match or more than one matching app registration.
4. **Expose the connector scope without replacing existing configuration.**
   Open **App registrations -> the exact Workday application -> Expose an API**.
   Preserve every unrelated existing scope and authorized client. Set
   the Application ID URI to `api://{entraAppId}`, add or repair only the
   `user_impersonation` scope, then add authorized client application
   `4e4707ca-5f53-46a6-a819-f7765446e6ff` for that scope.
5. **Add delegated permissions.** Open **App registrations -> the exact
   Workday application -> API permissions -> Add a permission -> Microsoft
   Graph -> Delegated permissions**. Add `openid`, `profile`, and `User.Read`,
   preserving unrelated existing permissions. Then select **Grant admin
   consent** using a consent-capable administrator.
6. **Configure assignment.** Open **Enterprise applications -> the exact
   Workday application -> Users and groups**. If assignment is required,
   assign the intended ESS employee security group; prefer a maintained group
   over individual users.
7. **Configure NameID.** Open **Enterprise applications -> the exact Workday
   application -> Single sign-on -> Attributes & Claims**. Edit **Unique User
   Identifier (Name ID)** so the source attribute equals the Workday User Name
   used by the tenant, commonly `user.mail` or `user.userPrincipalName`.

After each change, reread the setting where Microsoft Graph exposes it. A
Graph or Azure CLI command is evidence only when it exits with code 0 and
returns valid JSON. Never record a check as verified from partial stdout after
a nonzero exit. Avoid multi-parameter Graph URLs that Windows command wrappers
can split; request the resource with one query parameter and filter the
returned JSON locally when necessary.

Do not ask for or use a broad "everything is done" confirmation as evidence.
After the Graph reread, use one structured form for only the settings Graph
cannot prove. Ask for the exact selected SAML signing option and the exact
NameID source attribute. Store each exact non-secret value as `observedValue`
in its check object. A reply such as "done", "all good", "continue", or
"proceed" is not evidence for either field and must not be converted into
administrator attestation.

Use this exact `vscode_askQuestions` form:

```json
[
  {
    "header": "NameID source",
    "question": "What exact source attribute is configured for Unique User Identifier (Name ID) in the Workday application's SAML Attributes & Claims?"
  },
  {
    "header": "SAML signing",
    "question": "What exact SAML Signing Option is selected under SAML Signing Certificate -> Edit?",
    "options": [
      { "label": "Sign SAML response and assertion" },
      { "label": "Sign SAML assertion" },
      { "label": "Sign SAML response" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave both answers unset. Do not label a factual value as recommended. After
the administrator submits the form, perform the Graph reread immediately; do
not add a separate **Verify now** confirmation.

The administrator performs those changes in the Microsoft Entra admin center.
After the administrator confirms completion, reread the application and
service principal and paired app registration through Microsoft Graph. Do not
mark a planned action as
complete from confirmation alone; require the reread to prove it where Graph
exposes the setting. Persist the selected directory, enterprise-application
and app-registration pairing, `entraAppId`, `entraAppObjectId`,
`entraServicePrincipalId`, `entraAppIdUri`, `workdaySamlEntityId`,
`microsoftEntraIdentifier`, `entraLoginUrl`, `replyUrl`, `scopeGuid`, and safe
certificate metadata. Never persist certificate contents.

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

Write the Graph reread directly to
`.local/connect/workday-da/entra-verification.json` using a structured
file-write tool, then run:

```powershell
python scripts/workday_connect.py record-entra --verification-file ".local\connect\workday-da\entra-verification.json"
```

The JSON must contain the Graph-authenticated `tenantId`, selected directory,
exact enterprise-application/app-registration pairing, Reply URL, Microsoft
Entra Identifier, Login URL, both application identifier URIs, the
`user_impersonation` scope GUID, safe certificate metadata, and one evidence
object for each check:

```json
{
  "tenantId": "00000000-0000-0000-0000-000000000000",
  "selectedDirectory": {
    "tenantId": "00000000-0000-0000-0000-000000000000",
    "displayName": "Contoso"
  },
  "application": {
    "displayName": "Workday",
    "appId": "11111111-1111-1111-1111-111111111111",
    "objectId": "22222222-2222-2222-2222-222222222222",
    "servicePrincipalId": "33333333-3333-3333-3333-333333333333",
    "identifierUris": [
      "http://www.workday.com/{workdayTenant}",
      "api://11111111-1111-1111-1111-111111111111"
    ]
  },
  "scopeGuid": "44444444-4444-4444-4444-444444444444",
  "replyUrl": "https://{approved-workday-reply-url}",
  "microsoftEntraIdentifier": "https://sts.windows.net/00000000-0000-0000-0000-000000000000/",
  "loginUrl": "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000000/saml2",
  "certificate": {
    "thumbprint": "{thumbprint}",
    "validFrom": "2026-01-01T00:00:00Z",
    "validTo": "2027-01-01T00:00:00Z"
  },
  "checks": {
    "samlMode": {
      "outcome": "verified",
      "provenance": "microsoft-graph"
    },
    "signingCertificate": {
      "outcome": "verified",
      "provenance": "microsoft-graph"
    },
    "connectorPreauthorized": {
      "outcome": "verified",
      "provenance": "microsoft-graph"
    },
    "graphDelegatedPermissions": {
      "outcome": "verified",
      "provenance": "microsoft-graph"
    },
    "adminConsent": {
      "outcome": "verified",
      "provenance": "microsoft-graph"
    },
    "userAssignment": {
      "outcome": "verified",
      "provenance": "microsoft-graph"
    },
    "nameId": {
      "outcome": "verified",
      "provenance": "microsoft-graph",
      "observedValue": "user.userPrincipalName"
    },
    "samlSigningOption": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation",
      "observedValue": "Sign SAML response and assertion"
    },
    "existingScopesPreserved": {
      "outcome": "verified",
      "provenance": "microsoft-graph",
      "observedValue": "preserved"
    },
    "authorizedClientsPreserved": {
      "outcome": "verified",
      "provenance": "microsoft-graph",
      "observedValue": "preserved"
    },
    "permissionsPreserved": {
      "outcome": "verified",
      "provenance": "microsoft-graph",
      "observedValue": "preserved"
    }
  }
}
```

Use administrator attestation only for a portal-only setting that Graph cannot
read. For the three preservation checks, use `preserved` when the required
setting already coexists with unrelated configuration and `remediated` when a
targeted repair was required without replacing unrelated values. The command
rejects a different tenant and incomplete or provenance-free evidence. Resume
by rereading available settings and showing only failed remediation, not by
repeating the full guide.
