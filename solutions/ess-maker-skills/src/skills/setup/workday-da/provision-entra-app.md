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
`objectId`, service-principal `servicePrincipalId`, and `identifierUris`, then
run:

```powershell
python scripts/workday_connect.py entra-handoff --discovery-json '{"applications":[{...}]}'
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
2. **Keep the two identifiers distinct.** The Workday SAML Service Provider ID
   is `http://www.workday.com/{workdayTenant}`. The Entra application ID URI is
   `api://{entraAppId}`. Never copy one into the other field.
3. **Expose the connector scope.** Open **App registrations -> the exact
   Workday application -> Expose an API**. Set the Application ID URI to
   `api://{entraAppId}`, add the `user_impersonation` scope, then add authorized
   client application `4e4707ca-5f53-46a6-a819-f7765446e6ff` for that scope.
4. **Add delegated permissions.** Open **App registrations -> the exact
   Workday application -> API permissions -> Add a permission -> Microsoft
   Graph -> Delegated permissions**. Add `openid`, `profile`, and `User.Read`,
   then select **Grant admin consent** using a consent-capable administrator.
5. **Configure assignment.** Open **Enterprise applications -> the exact
   Workday application -> Users and groups**. If assignment is required,
   assign the intended ESS employee security group; prefer a maintained group
   over individual users.
6. **Configure NameID.** Open **Enterprise applications -> the exact Workday
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
NameID source attribute. A reply such as "done", "all good", "continue", or
"proceed" is not evidence for either field and must not be converted into
administrator attestation.

The administrator performs those changes in the Microsoft Entra admin center.
After the administrator confirms completion, reread the application and
service principal through Microsoft Graph. Do not mark a planned action as
complete from confirmation alone; require the reread to prove it where Graph
exposes the setting. Persist `entraAppId`,
`entraAppObjectId`, `entraAppIdUri`, `workdaySamlEntityId`, `scopeGuid`, and
safe certificate metadata under `identifiers`. Never persist certificate
contents.

For a portal-only setting that Graph cannot prove, include its non-secret
administrator confirmation in the `checks` object rather than claiming the
skill changed it.

Pass the Graph reread as:

```powershell
python scripts/workday_connect.py record-entra --verification-json '{...}'
```

The JSON must contain the Graph-authenticated `tenantId`, exact application and
service-principal identity, both identifier URIs, the `user_impersonation`
scope GUID, safe certificate metadata, and one evidence object for each check:

```json
{
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
      "provenance": "microsoft-graph"
    },
    "samlSigningOption": {
      "outcome": "confirmed",
      "provenance": "administrator-attestation"
    }
  }
}
```

Use administrator attestation only for a portal-only setting that Graph cannot
read. The command rejects a different tenant and incomplete or provenance-free
evidence. Resume by rereading available settings and showing only failed
remediation, not by repeating the full guide.
