<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phase 2 - Microsoft Entra

This phase discovers and plans one exact Workday SAML application, then guides
an administrator through the approved Entra changes and verifies the result.
It requires an Application Administrator or Cloud Application Administrator;
administrator consent may require a consent-capable role.

`workday_connect.py` has no `entra-apply` command. It validates discovery,
builds and hashes the exact plan, protects approval, and records state; it does
not create or modify the Entra application. Do not say that the skill will
create, configure, update, grant, or enable an Entra setting.

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

## Administrator apply, then skill verify

Immediately before presenting the handoff, run `verify-plan` with the current
plan and approved hash. Present only these approved administrator actions:

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

Record Graph-verified actions with `complete-action`. For a portal-only setting
that Graph cannot prove, record one explicit administrator handoff and its
non-secret confirmation rather than claiming the skill changed it. Set the
phase to `complete` only after all required evidence is present; otherwise set
it to `waiting`. Resume by rereading available settings, not by repeating all
instructions.
