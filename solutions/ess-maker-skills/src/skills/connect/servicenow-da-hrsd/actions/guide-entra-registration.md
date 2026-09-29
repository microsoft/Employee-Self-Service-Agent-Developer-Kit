# Guide and verify the Entra User Login application

Treat Entra registration as one complete high-level setup step. Give the Maker
the entire runbook below, identify the admin owner, explain the final evidence
to bring back, then pause exactly once. Do not pause between Create App,
claims, scope, pre-authorization, permissions, and consent.

This is always an admin-owned guided workflow. Never run `az ad app create`,
Graph `POST`/`PATCH`, admin-consent mutation, or any equivalent write
operation. Never request or persist a client secret, certificate, password,
token, or PFX.

## Goal and owner

- **Goal:** configure one single-tenant App A so the Power Platform ServiceNow
  connector can request delegated user tokens accepted by ServiceNow.
- **Owner role:** Global Administrator or Cloud App Administrator, with an
  appropriately authorized admin granting tenant-wide consent.

## Complete admin instructions

1. In Microsoft Entra admin center, open **Identity -> Applications -> App
   registrations -> New registration**. Create or identify one single-tenant
   app; no redirect URI is required.
2. In **Token configuration -> Add optional claim -> Access**, add `email`
   and `upn`.
3. In **Expose an API**, set Application ID URI to
   `api://<application-client-id>` and add an enabled delegated
   `user_impersonation` scope.
4. In **Authorized client applications**, add ServiceNow connector app
   `c26b24aa-7874-4e06-ad55-7d06b1f79b63` and select the exact
   `user_impersonation` scope.
5. In **API permissions**, add Microsoft Graph delegated permissions
   `openid`, `profile`, and `User.Read`.
6. Select **Grant admin consent** for the tenant.

## Completion signal and evidence

The Maker should return once, after all six operations are complete, with:

- only the non-secret Application (client) ID; and
- confirmation that claims, API scope, connector pre-authorization, Graph
  permissions, and tenant-wide admin consent are complete.

Ask one completion question for the whole Entra registration step. While the
question is pending, do not return an action result. If the admin is not done,
return `ACTION_RESULT = "waiting"`.

After completion, validate the Application client ID as a GUID, then record
one bundled phase handoff:

```text
python scripts/connect_servicenow_da.py record-admin-phase --phase entra-registration --status <completed|reused> --client-id <application-client-id>
```

Then run all six read-only Graph checkpoints. A `Failed` or `Error` result is
authoritative and cannot be overridden by the completion confirmation:

```text
python scripts/flightcheck/cli.py --checkpoint SN-DA-HRSD-ENTRA-APP-001 --agent-slug "{AGENT_SLUG}"
python scripts/flightcheck/cli.py --checkpoint SN-DA-HRSD-ENTRA-CLAIMS-001 --agent-slug "{AGENT_SLUG}"
python scripts/flightcheck/cli.py --checkpoint SN-DA-HRSD-ENTRA-SCOPE-001 --agent-slug "{AGENT_SLUG}"
python scripts/flightcheck/cli.py --checkpoint SN-DA-HRSD-ENTRA-PREAUTH-001 --agent-slug "{AGENT_SLUG}"
python scripts/flightcheck/cli.py --checkpoint SN-DA-HRSD-ENTRA-PERMISSIONS-001 --agent-slug "{AGENT_SLUG}"
python scripts/flightcheck/cli.py --checkpoint SN-DA-HRSD-ENTRA-CONSENT-001 --agent-slug "{AGENT_SLUG}"
```

Return `ACTION_RESULT = "recorded"` only when the whole step has current
evidence and none of its read-only checks reports `Failed` or `Error`.
