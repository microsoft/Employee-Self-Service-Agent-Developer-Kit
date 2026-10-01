# Guide and verify the Entra User Login application

Treat Entra registration as one complete high-level setup step. Give the Maker
the entire runbook below, identify the admin owner, explain the final evidence
to bring back, then pause exactly once. Do not pause between Create App,
claims, scope, pre-authorization, permissions, and consent.

This is always an admin-owned guided workflow. Never run `az ad app create`,
Graph `POST`/`PATCH`, admin-consent mutation, or any equivalent write
operation. Never request or persist a client secret, certificate, password,
token, or PFX.

Read `adminSetup.phaseHandoffs.entra-registration` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, do not ask again; return
`ACTION_RESULT = "recorded"` and let all six Graph checkpoints reverify the
current app. A prior `Failed`/`Error` or any other result outside
`completionStatuses` requires one new complete Entra handoff so the Maker can
return corrected bundled evidence.

## Goal and owner

- **Goal:** configure one single-tenant App A so the Power Platform ServiceNow
  connector can request delegated user tokens accepted by ServiceNow.
- **Owner role:** Application Administrator, Cloud Application Administrator,
  Privileged Role Administrator, or Global Administrator. An application
  owner may collaborate on app settings, but the phase still requires an
  appropriately authorized admin to grant tenant-wide consent.

## Complete admin instructions

Open the stable portal root once:

[Open Microsoft Entra admin center](https://entra.microsoft.com/)

1. Open `Identity` → `Applications` → `App registrations`. Resolve the
   single-tenant app by persisted Application client ID first,
   then by PR #217's deterministic display name
   `ESS Copilot - ServiceNow OIDC (<instance-name>)`.
   - If one exact app exists and is healthy, reuse it.
   - If one exact app exists but any required setting below is missing or
     unhealthy, repair that same app; do not create a duplicate.
   - If multiple exact matches exist, the Entra admin resolves the intended
     app inside this same high-level handoff and returns the selected client ID
     only with the final completion response. Do not add an intermediate
     selection pause.
   - Only when no exact app exists, select `New registration` and create it;
     no redirect URI is required.
2. In `Token configuration` → `Add optional claim` → `Access`, add `email`
   and `upn`.
3. In `Expose an API`, set Application ID URI to
   `api://<application-client-id>` and add an enabled delegated
   `user_impersonation` scope.
4. In `Authorized client applications`, add ServiceNow connector app
   `c26b24aa-7874-4e06-ad55-7d06b1f79b63` and select the exact
   `user_impersonation` scope.
5. In `API permissions`, add Microsoft Graph delegated permissions
   `openid`, `profile`, and `User.Read`.
6. Select `Grant admin consent` for the tenant.

## Completion signal and evidence

The Maker should return once, after all six operations are complete, with:

- only the non-secret Application (client) ID; and
- confirmation that claims, API scope, connector pre-authorization, Graph
  permissions, and tenant-wide admin consent are complete.

Ask one completion question for the whole Entra registration step. While the
question is pending, do not return an action result. If the admin is not done,
return `ACTION_RESULT = "waiting"`.

After verification or completion, validate the Application client ID as a
GUID, then record one bundled phase handoff. Use `reused` for a valid existing
app and `completed` for an app that required configuration:

```text
python scripts/connect_servicenow_da.py record-admin-phase --phase entra-registration --status <completed|reused> --client-id <application-client-id>
```

Do not call FlightCheck from this action document. Runner-owned checkpoint
target: `SN-DA-HRSD-ENTRA-*`. Return the action result below and let lifecycle
runner L.4b invoke that registered family once.

Do not run the six checkpoint IDs as separate CLI processes. The family
invocation preserves their individual IDs, statuses, results, and remediation
while sharing one category evaluation and one logical set of read-only API
calls. A `Failed` or `Error` result is authoritative and cannot be overridden
by the completion confirmation.

Return `ACTION_RESULT = "recorded"` after the bundled phase handoff is
persisted. Do not decide checkpoint success in this action: lifecycle runner
L.4b invokes the family once, and its six member results are authoritative for
phase completion or blocking.
