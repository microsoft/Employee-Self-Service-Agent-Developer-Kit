<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phase 2 - Microsoft Entra

This phase configures one exact Workday SAML application. It requires an
Application Administrator or Cloud Application Administrator; administrator
consent may require a consent-capable role.

## Discover before approval

1. Read the canonical Entra tenant ID and Workday tenant from controller state.
   If the Workday tenant is missing, ask for the signed-in Workday URL and
   validate its first path segment against
   `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`, then merge it into `scope` as
   `workdayTenant`.
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
python scripts/workday_connect.py entra-plan --discovery-json '{...}'
```

If no exact app exists, include `"allowCreate": true` only after the user
chooses to create the Workday gallery app. If multiple apps have the exact
Service Provider ID, stop for administrator remediation.

Show the returned target, Service Provider ID, Entra Application ID URI,
permissions, and actions. Obtain one approval for this exact plan, then store
it:

```powershell
python scripts/workday_connect.py approve-plan --phase entra --plan-json '{...}'
```

## Apply and verify

Immediately before each Graph mutation, run `verify-plan` with the current
plan and approved hash. Apply only the approved actions:

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

Reread the application and service principal. Persist `entraAppId`,
`entraAppObjectId`, `entraAppIdUri`, `workdaySamlEntityId`, `scopeGuid`, and
safe certificate metadata under `identifiers`. Never persist certificate
contents.

Record verified actions with `complete-action`, then set the `entra` phase to
`complete`. If a portal-only setting remains, record one explicit handoff and
set the phase to `waiting`; resume by rereading the setting, not by repeating
all instructions.
