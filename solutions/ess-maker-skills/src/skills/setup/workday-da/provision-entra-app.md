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
python scripts/workday_connect.py entra-handoff --discovery-json '{...}'
```

If no exact app exists, include `"allowCreate": true` only after the user
chooses to create the Workday gallery app. If multiple apps have the exact
Service Provider ID, stop for administrator remediation.

Show the returned target, Service Provider ID, Entra Application ID URI,
permissions, and administrator actions once as one handoff. Do not add a
separate apply approval: the controller does not perform these portal changes.

## Administrator apply, then skill verify

Present only these administrator actions:

- reuse the exact app or instantiate the Workday gallery app;
- configure SAML mode and the signing certificate;
- retain both distinct identifier URIs:
  - Workday SAML Service Provider ID:
    `http://www.workday.com/{workdayTenant}`
  - Entra Application ID URI: `api://{entraAppId}`
- expose `user_impersonation`;
- pre-authorize Workday connector app
  `4e4707ca-5f53-46a6-a819-f7765446e6ff`;
- add `openid`, `profile`, and `User.Read`;
- grant administrator consent;
- configure user assignment, NameID, and SAML signing as required.

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

The JSON must contain the exact application and service-principal identity,
both identifier URIs, the `user_impersonation` scope GUID, safe certificate
metadata, and true verification flags for SAML mode, signing certificate,
connector preauthorization, delegated permissions, administrator consent, and
user assignment/NameID. The command validates and completes the phase
atomically. If evidence is incomplete, record one handoff and leave the phase
waiting. Resume by rereading available settings, not by repeating all
instructions.
